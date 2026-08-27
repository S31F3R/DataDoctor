# Config.py
# Global configuration variables for DataDoctor

debug = False
utcOffset = ""
retroMode = False
qaqcEnabled = True
rawData = False
fontSize = 0  # Active base UI point size
uiFontFamily = ""  # Active UI font family
defaultFontLoaded = False  # True if bundled Noto Sans registered
retroFontLoaded = False  # True if Press Start 2P registered
periodOffset = True
sortState = {}
appRoot = ""
deltaChecked = False
overlayChecked = False
systemTextColor = ""
colorTheme = "system"  # system | light | dark (Options → Appearance)
labelDataTypeUSBR = True
labelDataTypeAquarius = True
labelDataTypeUSGS = True

# Oracle / HDB credential policy (Options → Oracle password change)
# Pre-12.2 Oracle max was 30 characters; keep 30 for HDB compatibility.
oraclePasswordMinLength = 12
oraclePasswordMaxLength = 30

# Oracle HDB databases: 'UI_LABEL|SCHEMA'
# Schema is query-only (not shown in comboboxes/labels). Display name is the part
# before '|'. TNS alias is still derived from the label (USBR-LCHDB → lchdb).
# Current rstrip logic is used only when a DB is not listed here.
# PNHYD / GPHYD are not included (not standard HDB Oracle write targets).
hdbOracleDatabases = (
    'USBR-LCHDB|LCHDBA',
    'USBR-YAOHDB|YAOHDBA',
    'USBR-UCHDB2|UCHDBA',
    'USBR-ECOHDB|ECODBA',
    'USBR-LBOHDB|LBOHDBA',
    'USBR-KBOHDB|KBOHDBA',
    'USBR-CUHDB|CUHDBA',
)

# ---------------------------------------------------------------------------
# HDB MODIFY_R_BASE write defaults
# OVERWRITE_FLAG comes from Options → USBR → Overwrite Flag ('O' or None/NULL).
# DO_UPDATE_Y_OR_N is always 'Y' (not exposed).
# DATA_FLAGS / TIME_ZONE default None → Oracle NULL.
# AGEN_ID will become a combo; TIME_ZONE needs HDB research.
# ---------------------------------------------------------------------------
hdbAgenId = 7
hdbCollectionSystemId = 5
hdbMethodId = 13
hdbLoadingApplicationId = 33
hdbComputationId = 1
hdbValidation = 'Z'
hdbDoUpdateYorN = 'Y'
hdbOverwriteFlag = None   # 'O' when Options Overwrite Flag is on; else NULL
hdbDataFlags = None       # None → NULL; future option
hdbTimeZone = None        # None → NULL; research later