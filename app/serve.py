"""Start the single-process SQLite application on Render or locally."""
import os
import uvicorn


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT deve ser um número entre 1 e 65535")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1, proxy_headers=False)


if __name__ == "__main__":
    main()
