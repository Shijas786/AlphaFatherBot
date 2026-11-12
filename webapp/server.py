import logging
from pathlib import Path
from aiohttp import web
import config
from webapp.routes import (
    api_get_user,
    api_update_settings,
    api_save_api_keys,
    api_get_trades,
    api_panic_sell,
    api_get_listings,
    api_get_server_ip
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=200)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return response

async def serve_index(request):
    """Serve the Mini App main SPA index.html."""
    index_file = STATIC_DIR / "index.html"
    return web.FileResponse(index_file)

def create_webapp() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])

    # API routes
    app.router.add_get("/api/user", api_get_user)
    app.router.add_post("/api/user/settings", api_update_settings)
    app.router.add_post("/api/user/api-keys", api_save_api_keys)
    app.router.add_get("/api/trades", api_get_trades)
    app.router.add_post("/api/trades/panic-sell", api_panic_sell)
    app.router.add_get("/api/listings", api_get_listings)
    app.router.add_get("/api/ip", api_get_server_ip)

    # Static assets
    app.router.add_get("/", serve_index)
    app.router.add_static("/static/", path=str(STATIC_DIR), name="static")

    return app

class WebAppRunner:
    def __init__(self):
        self.runner = None
        self.site = None

    async def start(self):
        app = create_webapp()
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, config.WEBAPP_HOST, config.WEBAPP_PORT)
        await self.site.start()
        logger.info(f"Telegram Mini App server listening on http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            logger.info("Telegram Mini App server stopped.")

webapp_runner = WebAppRunner()

