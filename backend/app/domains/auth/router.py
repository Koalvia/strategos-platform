from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

from . import models, schemas, service, utils

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.MessageResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: schemas.UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user. Sends verification email.
    """
    auth_service = service.AuthService(db)
    user = auth_service.register_user(user_data)
    return {"message": f"Registration successful. Please check {user.email} for verification link."}


@router.post("/login", response_model=schemas.Token)
def login(user_data: schemas.UserLogin, response: Response, db: Session = Depends(get_db)):
    """
    Login user and return JWT token. Requires verified email.
    """
    auth_service = service.AuthService(db)
    token_data = auth_service.login_user(user_data)

    # Set HTTP-only cookie (optional, for additional security)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token_data['access_token']}",
        httponly=True,
        secure=True,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=1800  # 30 minutes
    )

    return token_data

def _require_sso_enabled():
    if not settings.MS_SSO_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/microsoft/login", response_model=schemas.MicrosoftLoginStart, dependencies=[Depends(_require_sso_enabled)])
def microsoft_login(db: Session = Depends(get_db)):
    """Return the Microsoft authorization URL and flow state."""
    return service.AuthService(db).microsoft_login_start()

@router.post("/microsoft/callback", response_model=schemas.Token, dependencies=[Depends(_require_sso_enabled)])
def microsoft_callback(data:schemas.MicrosoftCallback, db: Session = Depends(get_db)):
    """Complete Microsoft sign-in and return a JWT."""
    return service.AuthService(db).login_with_microsoft(data.flow, data.auth_response)

@router.post("/logout", response_model=schemas.MessageResponse)
def logout(response: Response):
    """
    Logout user by clearing the cookie.
    """
    response.delete_cookie(key="access_token")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(utils.get_verified_user)):
    """
    Get current authenticated user information.
    """
    return current_user


@router.post("/verify-email", response_model=schemas.MessageResponse)
def verify_email(data: schemas.VerifyEmail, db: Session = Depends(get_db)):
    """
    Verify user email with token sent via email.
    """
    auth_service = service.AuthService(db)
    auth_service.verify_email(data.token)
    return {"message": "Email verified successfully. You can now log in."}


@router.post("/forgot-password", response_model=schemas.MessageResponse)
def forgot_password(data: schemas.ForgotPassword, db: Session = Depends(get_db)):
    """
    Request password reset. Sends reset link to email.
    """
    auth_service = service.AuthService(db)
    auth_service.forgot_password(data.email)
    return {"message": "If the email exists, a password reset link has been sent."}


@router.post("/reset-password", response_model=schemas.MessageResponse)
def reset_password(data: schemas.ResetPassword, db: Session = Depends(get_db)):
    """
    Reset password using token from email.
    """
    auth_service = service.AuthService(db)
    auth_service.reset_password(data.token, data.new_password)
    return {"message": "Password reset successfully. You can now log in with your new password."}
