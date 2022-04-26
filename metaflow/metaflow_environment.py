import os
import platform
import sys

from .util import get_username
from . import metaflow_version
from metaflow.exception import MetaflowException
from metaflow.extension_support import dump_module_info
from metaflow.mflog import BASH_MFLOG, BASH_MFLOG_KFP
from . import R

version_cache = None


class InvalidEnvironmentException(MetaflowException):
    headline = "Incompatible environment"


class MetaflowEnvironment(object):
    TYPE = "local"

    def __init__(self, flow):
        pass

    def init_environment(self, echo):
        """
        Run before any step decorators are initialized.
        """
        pass

    def validate_environment(self, echo):
        """
        Run before any command to validate that we are operating in
        a desired environment.
        """
        pass

    def decospecs(self):
        """
        Environment may insert decorators, equivalent to setting --with
        options on the command line.
        """
        return ()

    def bootstrap_commands(self, step_name):
        """
        A list of shell commands to bootstrap this environment in a remote runtime.
        """
        return []

    def add_to_package(self):
        """
        A list of tuples (file, arcname) to add to the job package.
        `arcname` is an alternative name for the file in the job package.
        """
        return []

    def pylint_config(self):
        """
        Environment may override pylint config.
        """
        return []

    @classmethod
    def get_client_info(cls, flow_name, metadata):
        """
        Environment may customize the information returned to the client about the environment

        Parameters
        ----------
        flow_name : str
            Name of the flow
        metadata : dict
            Metadata information regarding the task

        Returns
        -------
        str : Information printed and returned to the user
        """
        return "Local environment"

    def get_boto3_copy_command(self, s3_path, local_path, command="download_file"):
        if command == "download_file":
            copy_command = (
                "boto3.client('s3')"
                ".download_file(parsed.netloc, parsed.path.lstrip('/'), '%s')"
                % local_path
            )
        elif command == "upload_file":
            copy_command = (
                "boto3.client('s3')"
                ".upload_file('%s', parsed.netloc, parsed.path.lstrip('/'))"
                % local_path
            )
        else:
            raise ValueError("%s not supported" % command)

        return (
            '%s -c "import boto3; ' % self._python()
            + "exec('try:\\n from urlparse import urlparse\\nexcept:\\n from urllib.parse import "
            "urlparse'); "
            + "parsed = urlparse('%s'); " % s3_path
            + '%s"' % copy_command
        )

    def get_package_commands(
        self,
        code_package_url,
        is_kfp_plugin=False,
    ):
        mflog_bash_cmd = BASH_MFLOG if not is_kfp_plugin else BASH_MFLOG_KFP
        cmds = [
            mflog_bash_cmd,
            "mflog 'Setting up task environment.'",
            "%s -m pip install requests boto3 -qqq" % self._python(),
            "mkdir metaflow",
            "cd metaflow",
            "mkdir .metaflow",  # mute local datastore creation log
            "i=0; while [ $i -le 5 ]; do "
            "mflog 'Downloading code package...'; "
            "%s && mflog 'Code package downloaded.' && break; "
            "sleep 10; i=$((i+1)); "
            "done" % self.get_boto3_copy_command(code_package_url, "job.tar"),
            "if [ $i -gt 5 ]; then "
            "mflog 'Failed to download code package from %s "
            "after 6 tries. Exiting...' && exit 1; "
            "fi" % code_package_url,
            "TAR_OPTIONS='--warning=no-timestamp' tar xf job.tar",
            "mflog 'Task is starting.'",
        ]
        return cmds

    def get_environment_info(self):
        global version_cache
        if version_cache is None:
            version_cache = metaflow_version.get_version()

        # note that this dict goes into the code package
        # so variables here should be relatively stable (no
        # timestamps) so the hash won't change all the time
        env = {
            "platform": platform.system(),
            "username": get_username(),
            "production_token": os.environ.get("METAFLOW_PRODUCTION_TOKEN"),
            "runtime": os.environ.get("METAFLOW_RUNTIME_NAME", "dev"),
            "app": os.environ.get("APP"),
            "environment_type": self.TYPE,
            "use_r": R.use_r(),
            "python_version": sys.version,
            "python_version_code": "%d.%d.%d" % sys.version_info[:3],
            "metaflow_version": version_cache,
            "script": os.path.basename(os.path.abspath(sys.argv[0])),
            # KFP plug-in info
            "pod_namespace": os.environ.get("MF_POD_NAMESPACE"),
            "zodiac_service": os.environ.get("ZODIAC_SERVICE"),
            "zodiac_team": os.environ.get("ZODIAC_TEAM"),
        }
        if R.use_r():
            env["metaflow_r_version"] = R.metaflow_r_version()
            env["r_version"] = R.r_version()
            env["r_version_code"] = R.r_version_code()
        # Information about extension modules (to load them in the proper order)
        ext_key, ext_val = dump_module_info()
        env[ext_key] = ext_val
        return env

    def executable(self, step_name):
        return self._python()

    def _python(self):
        if R.use_r():
            return "python3"
        else:
            return "python"
