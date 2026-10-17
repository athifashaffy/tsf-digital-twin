"""Builds the booth pages from tsf-digital-twin.html:
   index.html      — operations console   (http://localhost:8600/)
   showcase.html   — cinematic loop        (http://localhost:8600/showcase.html)
   tsf-showcase.html — artifact copy of the showcase"""
from pathlib import Path
d = Path(__file__).parent
src = (d / "tsf-digital-twin.html").read_text()
head_end = src.index("</style>") + len("</style>")
FLAG = "<script>window.TWIN_SHOWCASE=true;</script>\n"

def page(body_prefix=""):
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            + src[:head_end] + "\n</head>\n<body>\n" + body_prefix + src[head_end:] + "\n</body>\n</html>\n")

(d / "index.html").write_text(page())
(d / "showcase.html").write_text(page(FLAG).replace("<title>TSF Digital Twin</title>", "<title>TSF-01 Showcase</title>"))
(d / "tsf-showcase.html").write_text(src.replace("<title>TSF Digital Twin</title>", "<title>TSF-01 Showcase</title>")
                                      .replace("</style>", "</style>\n" + FLAG, 1))
print("built index.html, showcase.html, tsf-showcase.html")
