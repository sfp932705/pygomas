import os

this_dir, _ = os.path.split(__file__)
DEFAULT_DATA_PATH = f"{this_dir}{os.sep}maps{os.sep}"

# Ontologies
ACTION: str = "ACTION"
AIM: str = "aim"
ANGLE: str = "angle"
CREATE: str = "CREATE"
DEC_AMMO: str = "dec_ammo"
DEC_HEALTH: str = "dec_health"
DESTROY: str = "DESTROY"
DISTANCE: str = "distance"
FOV: str = "fov"
HEAD_X: str = "headx"
HEAD_Y: str = "heady"
HEAD_Z: str = "headz"
MAP: str = "map"
PACKS: str = "PACKS"
QTY: str = "qty"
SHOTS: str = "shots"
VEL_X: str = "xvel"
TYPE: str = "type"
VEL_Y: str = "yvel"
VEL_Z: str = "zvel"
X: str = "x"
Y: str = "y"
Z: str = "z"

# Performatives
PERFORMATIVE: str = "performative"
PERFORMATIVE_BDI: str = "BDI"
PERFORMATIVE_CFA: str = "cfa"
PERFORMATIVE_CFB: str = "cfb"
PERFORMATIVE_CFM: str = "cfm"
PERFORMATIVE_DATA: str = "data"
PERFORMATIVE_DEREGISTER_AGENT: str = "deregister_agent"
PERFORMATIVE_DEREGISTER_SERVICE: str = "deregister_service"
PERFORMATIVE_GAME: str = "game"
PERFORMATIVE_GET: str = "get"
PERFORMATIVE_INFORM: str = "inform"
PERFORMATIVE_INIT: str = "init"
PERFORMATIVE_MOVE: str = "move"
PERFORMATIVE_OBJECTIVE: str = "objective"
PERFORMATIVE_PACK: str = "pack"
PERFORMATIVE_PACK_LOST: str = "pack_lost"
PERFORMATIVE_REGISTER_AGENT: str = "register_agent"
PERFORMATIVE_REGISTER_SERVICE: str = "register"
PERFORMATIVE_SERVICES: str = "services"
PERFORMATIVE_SIGHT: str = "sight"
PERFORMATIVE_SHOOT: str = "shot"

# Precisions
PRECISION_Z = 0.5
PRECISION_X = 0.5

# Services
AMMO_SERVICE: str = "fieldops"
BACKUP_SERVICE: str = "backup"
MANAGEMENT_SERVICE: str = "management"
MEDIC_SERVICE: str = "medic"

# Teams
TEAM_NONE: int = 0
TEAM_ALLIED: int = 100
TEAM_AXIS: int = 200

# Set of beliefs
AMMO: str = "ammo"
BASE: str = "base"
CONTROL_POINTS: str = "control_points"
DESTINATION: str = "destination"
ENEMIES_IN_FOV: str = "enemies_in_fov"
FRIENDS_IN_FOV: str = "friends_in_fov"
FLAG: str = "flag"
HEADING: str = "heading"
HEALTH: str = "health"
NAME: str = "name"
MY_MEDICS: str = "myMedics"
MY_FIELDOPS: str = "myFieldops"
MY_BACKUPS: str = "myBackups"
PACKS_IN_FOV: str = "packs_in_fov"
PERFORMATIVE_PACK_TAKEN: str = "pack_taken"
PERFORMATIVE_TARGET_REACHED: str = "target_reached"
PERFORMATIVE_FLAG_TAKEN: str = "flag_taken"
POSITION: str = "position"
TEAM: str = "team"
THRESHOLD_HEALTH: str = "threshold_health"
THRESHOLD_AMMO: str = "threshold_ammo"
THRESHOLD_AIM: str = "threshold_aim"
THRESHOLD_SHOTS: str = "threshold_shots"
VELOCITY: str = "velocity"


MSGPACK_AGENTS: int = 10
MSGPACK_PACKS: int = 11
MSGPACK_NAME: int = 12
MSGPACK_TYPE: int = 13
MSGPACK_TEAM: int = 14
MSGPACK_HEALTH: int = 15
MSGPACK_AMMO: int = 16
MSGPACK_IS_CARRYING: int = 17
MSGPACK_POSITION: int = 18
MSGPACK_VELOCITY: int = 19
MSGPACK_HEADING: int = 20


class Config(object):
    def __init__(self, data_path=None):
        self.data_path = data_path if data_path else DEFAULT_DATA_PATH
        if not self.data_path.endswith(os.sep):
            self.data_path += os.sep

    def set_data_path(self, data_path):
        self.data_path = data_path
        if not self.data_path.endswith(os.sep):
            self.data_path += os.sep
