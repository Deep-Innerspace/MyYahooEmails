"""Web dashboard route registry."""
from fastapi import APIRouter

from src.web.routes.dashboard import router as dashboard_router
from src.web.routes.emails import router as emails_router
from src.web.routes.notes import router as notes_router
from src.web.routes.charts import router as charts_router
from src.web.routes.timeline import router as timeline_router
from src.web.routes.analysis import router as analysis_router
from src.web.routes.contacts import router as contacts_router
from src.web.routes.reports import router as reports_router
from src.web.routes.settings import router as settings_router
from src.web.routes.book import router as book_router
from src.web.routes.procedures import router as procedures_router
from src.web.routes.attachments import router as attachments_router
from src.web.routes.invoices import router as invoices_router
from src.web.routes.sync import router as sync_router
from src.web.routes.reply import router as reply_router
from src.web.routes.memories import router as memories_router

router = APIRouter()
router.include_router(dashboard_router)
router.include_router(emails_router, prefix="/emails")
router.include_router(notes_router, prefix="/notes")
router.include_router(charts_router, prefix="/charts")
router.include_router(timeline_router, prefix="/timeline")
router.include_router(analysis_router, prefix="/analysis")
router.include_router(contacts_router, prefix="/contacts")
router.include_router(reports_router, prefix="/reports")
router.include_router(settings_router, prefix="/settings")
router.include_router(book_router)
router.include_router(procedures_router, prefix="/procedures")
router.include_router(attachments_router, prefix="/attachments")
router.include_router(invoices_router, prefix="/invoices")
router.include_router(sync_router)
router.include_router(reply_router)
router.include_router(memories_router)
