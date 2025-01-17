from typing import Dict
from metaflow._vendor import click
import logging

from metaflow.plugins.aip import run_id_to_url

_logger = logging.getLogger(__name__)


@click.command()
@click.option("--flow_name")
@click.option("--status")
@click.option("--run_id")
@click.option("--argo_workflow_uid")
@click.option("--env_variables_json")
@click.option("--flow_parameters_json")
@click.option("--run_email_notify", is_flag=True, default=False)
@click.option("--run_sqs_on_error", is_flag=True, default=False)
def exit_handler(
    flow_name: str,
    status: str,
    run_id: str,
    argo_workflow_uid: str,
    env_variables_json: str,
    flow_parameters_json: str,
    run_email_notify: bool = False,
    run_sqs_on_error: bool = False,
):
    """
    The environment variables that this depends on:
        METAFLOW_NOTIFY_ON_SUCCESS
        METAFLOW_NOTIFY_ON_ERROR
        METAFLOW_NOTIFY_EMAIL_SMTP_HOST
        METAFLOW_NOTIFY_EMAIL_SMTP_PORT
        METAFLOW_NOTIFY_EMAIL_FROM
        METAFLOW_SQS_URL_ON_ERROR
        METAFLOW_SQS_ROLE_ARN_ON_ERROR
        K8S_CLUSTER_ENV
        POD_NAMESPACE
        MF_ARGO_WORKFLOW_NAME
        METAFLOW_NOTIFY_EMAIL_BODY
    """
    import json
    import os
    import boto3
    from botocore.session import Session

    env_variables: Dict[str, str] = json.loads(env_variables_json)

    def get_env(name, default=None) -> str:
        return env_variables.get(name, os.environ.get(name, default=default))

    def email_notify(send_to):
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.utils import formatdate

        smtp_host = get_env("METAFLOW_NOTIFY_EMAIL_SMTP_HOST")
        smtp_port = int(get_env("METAFLOW_NOTIFY_EMAIL_SMTP_PORT"))
        email_from = get_env("METAFLOW_NOTIFY_EMAIL_FROM")
        cluster_env = get_env("K8S_CLUSTER_ENV", "")

        msg = MIMEMultipart(mime_subtype="mixed")
        msg["Subject"] = f"Flow {flow_name} {status} on {cluster_env}"
        msg["From"] = email_from
        msg["To"] = send_to
        msg["Date"] = formatdate(localtime=True)

        argo_workflow_name = get_env("MF_ARGO_WORKFLOW_NAME", "")
        email_body = get_env("METAFLOW_NOTIFY_EMAIL_BODY", "")
        k8s_namespace = get_env("POD_NAMESPACE", "")

        argo_ui_url = run_id_to_url(
            argo_workflow_name, k8s_namespace, argo_workflow_uid
        )
        body = (
            f"status = {status} <br/>\n"
            f"{argo_ui_url} <br/>\n"
            f"Metaflow RunId = {run_id} <br/>\n"
            f"argo -n {k8s_namespace} get {argo_workflow_name} <br/>"
            "<br/>"
            f"{email_body}"
        )
        mime_text = MIMEText(body, "html")
        msg.attach(mime_text)

        s = smtplib.SMTP(smtp_host, smtp_port)
        s.sendmail(email_from, send_to, msg.as_string())
        s.quit()
        print(msg)

    def get_aws_session(role_arn: str = None) -> Session:
        from botocore.credentials import (
            AssumeRoleCredentialFetcher,
            DeferredRefreshableCredentials,
        )

        region_name = "us-west-2"
        source_session = boto3.Session(region_name=region_name)

        if role_arn is None:
            return source_session

        # Fetch assumed role's credentials
        fetcher = AssumeRoleCredentialFetcher(
            client_creator=source_session._session.create_client,
            source_credentials=source_session.get_credentials(),
            role_arn=role_arn,
        )

        # Create new session with assumed role and auto-refresh
        botocore_session = Session()
        botocore_session._credentials = DeferredRefreshableCredentials(
            method="assume-role",
            refresh_using=fetcher.fetch_credentials,
        )

        return boto3.Session(botocore_session=botocore_session, region_name=region_name)

    def send_sqs_message(queue_url: str, message_body: str, *, role_arn: str = None):
        try:
            # Create session from given iam role
            session = get_aws_session(role_arn)

            # Create an SQS client from the session
            sqs = session.client("sqs")

            # Send message to SQS queue
            response = sqs.send_message(QueueUrl=queue_url, MessageBody=message_body)

            _logger.debug(
                f"Successfully sent the message {message_body} "
                f"to sqs {queue_url} with MessageId {response['MessageId']}"
            )
        except Exception as err:
            _logger.error(
                f"Failed to send the message {message_body} to sqs {queue_url}"
            )
            _logger.error(err)
            raise err

    print(f"Flow completed with status={status}")
    if run_email_notify:
        notify_on_error = get_env("METAFLOW_NOTIFY_ON_ERROR")
        notify_on_success = get_env("METAFLOW_NOTIFY_ON_SUCCESS")

        # AIP-8098 ExitHandler and Ops notification NOT called on Workflow.status == Error
        #   available statuses of Succeeded, Failed, Error
        if notify_on_success and status == "Succeeded":
            email_notify(notify_on_success)
        elif notify_on_error:
            email_notify(notify_on_error)
        else:
            print("No notification is necessary!")

    if run_sqs_on_error:
        # Send message to SQS if 'METAFLOW_SQS_URL_ON_ERROR' is set
        metaflow_sqs_url_on_error = get_env("METAFLOW_SQS_URL_ON_ERROR")

        if metaflow_sqs_url_on_error:
            if status == "Succeeded":
                print("Workflow succeeded, thus no SQS message is sent to SQS!")
            else:
                message_body = flow_parameters_json
                metaflow_sqs_role_arn_on_error = get_env(
                    "METAFLOW_SQS_ROLE_ARN_ON_ERROR"
                )
                send_sqs_message(
                    metaflow_sqs_url_on_error,
                    message_body,
                    role_arn=metaflow_sqs_role_arn_on_error,
                )
                print(f"message was sent to: {metaflow_sqs_url_on_error} successfully")
        else:
            print("SQS is not configured!")


if __name__ == "__main__":
    exit_handler()
