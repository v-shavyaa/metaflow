# Constants used in run MF flow on KFP

# Defaults for running MF on KFP
BASE_IMAGE = "hsezhiyan/metaflow-zillow:2.0"


KFP_METAFLOW_FOREACH_SPLITS_PATH = "/tmp/kfp_metaflow_foreach_splits_dict.json"

SPLIT_INDEX_SEPARATOR = "_"
PASSED_IN_SPLIT_INDEXES_ENV_NAME = "PASSED_IN_SPLIT_INDEXES_ENV_NAME"
TASK_ID_ENV_NAME = "TASK_ID_ENV_NAME"
SPLIT_INDEX_ENV_NAME = "SPLIT_INDEX_ENV_NAME"
INPUT_PATHS_ENV_NAME = "INPUT_PATHS_ENV_NAME"
