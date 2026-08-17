import uvicorn

from admin.app.config import get_settings
from admin.app.main import create_app

settings = get_settings()
app = create_app(settings)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
