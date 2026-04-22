MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

MAX_INSTRUCTIONS_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_INSTRUCTIONS_EXTENSIONS = {".pdf", ".txt"}


BGG_IMPORT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BGG_PLAYS_MAX_BYTES = 20 * 1024 * 1024  # 20 MB

NOTES_MAX_LENGTH = 2000  # max chars for user_notes / session notes fields

CSV_IMPORT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

# Sentinel passed as ?location=__none__ to match games with no storage
# location set (NULL or empty string). Mirrored in frontend/js/app.js.
NO_LOCATION_SENTINEL = "__none__"
