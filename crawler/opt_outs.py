"""Owner requests to keep repositories out of automatic indexing."""

# Keep these accounts excluded until their owners ask to resume indexing.
# Owners can still submit curated links themselves through a pull request.
OPTED_OUT_OWNERS = {"hwy0507"}


def is_opted_out(full_name):
    return full_name.partition("/")[0].lower() in OPTED_OUT_OWNERS
