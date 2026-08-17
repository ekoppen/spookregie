from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from admin.app.auth import check_password

router = APIRouter()


class LoginRequest(BaseModel):
    password: str


@router.post("/api/login")
def login(body: LoginRequest, request: Request, response: Response):
    settings = request.app.state.settings
    if not check_password(body.password, settings.admin_password):
        return Response(status_code=401)
    token = request.app.state.sessions.create()
    response.set_cookie("session", token, httponly=True)
    return {"ok": True}


@router.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session")
    if token:
        request.app.state.sessions.revoke(token)
    response.delete_cookie("session")
    return {"ok": True}
