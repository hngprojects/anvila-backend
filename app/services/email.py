async def send_verification_email(email: str, verification_url: str) -> None:
    print(f"[DEV] Verify email link for {email}: {verification_url}", flush=True)
