"""Branding: church name, button color and logo (admin only to change)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models as m
from ..branding import MAX_LOGO_UPLOAD_BYTES, LogoError, build_palette, contrast_ratio, normalize_logo
from ..config_store import load_general
from ..netutil import client_ip
from .auth import AuthContext, require_admin, require_user
from .deps import audit, config_changed, get_db, get_redis
from .schemas import BrandingIn

router = APIRouter(prefix="/api/branding", tags=["branding"])


async def _branding(db: AsyncSession) -> dict:
    general = await load_general(db)
    logo = await db.get(m.BrandingAsset, "logo")
    palette = build_palette(general["accent_color"])
    return {
        "church_name": general["church_name"],
        "accent_color": general["accent_color"],
        "palette": palette,
        "contrast": {shade: round(contrast_ratio(palette[shade], "#FFFFFF"), 2) for shade in ("500", "600", "700", "800")},
        "logo": {"sha256": logo.sha256, "updated_at": logo.updated_at.isoformat() if logo.updated_at else None,
                 "bytes": len(logo.content)} if logo else None,
    }


@router.get("")
async def get_branding(ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    return await _branding(db)


@router.put("")
async def put_branding(body: BrandingIn, request: Request, ctx: AuthContext = Depends(require_admin),
                       db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    row = await db.get(m.AppSetting, "general")
    current = dict(row.value) if row else {}
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "accent_color" in changes:
        changes["accent_color"] = changes["accent_color"].upper()
    current.update(changes)
    if row is None:
        db.add(m.AppSetting(key="general", value=current))
    else:
        row.value = current
    await db.commit()
    await audit(db, ctx, "branding_updated", "branding", ip=client_ip(request), changes=changes)
    await config_changed(redis)
    return await _branding(db)


@router.get("/logo")
async def get_logo(ctx: AuthContext = Depends(require_user), db: AsyncSession = Depends(get_db)):
    logo = await db.get(m.BrandingAsset, "logo")
    if not logo:
        raise HTTPException(404, "No logo uploaded")
    return Response(logo.content, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.put("/logo")
async def upload_logo(request: Request, ctx: AuthContext = Depends(require_admin),
                      db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    """Upload a PNG as the raw request body (Content-Type: image/png)."""
    if request.headers.get("content-type", "").split(";")[0].strip() != "image/png":
        raise HTTPException(415, "Upload a PNG image (Content-Type: image/png)")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_LOGO_UPLOAD_BYTES:
        raise HTTPException(413, "Logo must be 5 MB or smaller")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_LOGO_UPLOAD_BYTES:
            raise HTTPException(413, "Logo must be 5 MB or smaller")
    try:
        png, sha = normalize_logo(bytes(data))
    except LogoError as e:
        raise HTTPException(422, str(e))
    logo = await db.get(m.BrandingAsset, "logo")
    if logo is None:
        db.add(m.BrandingAsset(key="logo", content=png, content_type="image/png", sha256=sha))
    else:
        logo.content, logo.sha256 = png, sha
    await db.commit()
    await audit(db, ctx, "logo_uploaded", "logo", ip=client_ip(request), sha256=sha, bytes=len(png))
    await config_changed(redis)
    return await _branding(db)


@router.delete("/logo")
async def delete_logo(request: Request, ctx: AuthContext = Depends(require_admin),
                      db: AsyncSession = Depends(get_db), redis=Depends(get_redis)):
    logo = await db.get(m.BrandingAsset, "logo")
    if logo:
        await db.delete(logo)
        await db.commit()
        await audit(db, ctx, "logo_removed", "logo", ip=client_ip(request))
        await config_changed(redis)
    return await _branding(db)
