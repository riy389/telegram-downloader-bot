from sources.x import is_x_url


def detect_source(url: str):
    if is_x_url(url):
        return "x"

    return "generic"
