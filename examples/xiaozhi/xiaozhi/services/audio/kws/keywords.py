import re

from sherpa_onnx import text2token


def init_project_context():
    """动态导入父模块"""
    import os
    import sys

    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../..")
    )
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


init_project_context()

from config import APP_CONFIG
from xiaozhi.utils.file import get_model_file_path


def get_args():
    tokens_type = "cjkchar+bpe"
    tokens = get_model_file_path("tokens.txt")
    bpe_model = get_model_file_path("bpe.model")
    output = get_model_file_path("keywords.txt")
    keywords = APP_CONFIG["wakeup"]["keywords"]
    thresholds = APP_CONFIG["wakeup"].get("keyword_thresholds") or {}
    texts = [f"{keyword.upper()}" for keyword in keywords]
    return locals()


def keyword_line(keyword, tokens, thresholds):
    """One keywords.txt line; `#t` overrides the spotter's threshold for this word only."""
    line = "".join(tokens)
    parts = [" ".join(tokens)]
    threshold = thresholds.get(keyword)
    if threshold is not None:
        parts.append(f"#{float(threshold)}")
    if not re.match(r"^[▁A-Z\s]+$", line):
        parts.append(f"@{line}")
    return " ".join(parts)


def main():
    args = get_args()
    for keyword in set(args["thresholds"]) - set(args["keywords"]):
        print(f"⚠️ keyword_thresholds 里的 {keyword!r} 不在 keywords 中，已忽略")
    encoded_texts = text2token(
        args["texts"],
        tokens=args["tokens"],
        tokens_type=args["tokens_type"],
        bpe_model=args["bpe_model"],
    )
    with open(args["output"], "w", encoding="utf8") as f:
        for keyword, txt in zip(args["keywords"], encoded_texts):
            f.write(keyword_line(keyword, txt, args["thresholds"]) + "\n")


if __name__ == "__main__":
    main()
