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
enableSQL = False

# Oracle / HDB credential policy (Options → USBR password change)
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
    'USBR-ECOHDB|ECOHDBA',
    'USBR-LBOHDB|LBOHDBA',
    'USBR-KBOHDB|KBOHDBA',
)

# ---------------------------------------------------------------------------
# HDB MODIFY_R_BASE write defaults (Options UI later for some of these)
# DO_UPDATE_Y_OR_N is always 'Y' (not exposed).
# OVERWRITE_FLAG / DATA_FLAGS / TIME_ZONE default None → Oracle NULL for now.
# AGEN_ID will become a combo; TIME_ZONE needs HDB research.
# ---------------------------------------------------------------------------
hdbAgenId = 7
hdbCollectionSystemId = 5
hdbMethodId = 13
hdbLoadingApplicationId = 33
hdbComputationId = 1
hdbValidation = 'Z'
hdbDoUpdateYorN = 'Y'
hdbOverwriteFlag = None   # None → NULL; future option may pass 'O'
hdbDataFlags = None       # None → NULL; future option
hdbTimeZone = None        # None → NULL; research later