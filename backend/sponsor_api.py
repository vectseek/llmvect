# -*- coding: utf-8 -*-
"""
LLM.中国 赞助商系统 - 独立模块
"""
import sqlite3
import os
import secrets
import hashlib
import httpx
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from models import LLM_PROVIDERS, BATTLE_MODELS

DB_PATH = os.path.join(os.path.dirname(__file__), "llm_china.db")
router = APIRouter(prefix="/api/sponsor", tags=["sponsor"])
SESSION_EXPIRE_DAYS = 30
BRAND_MAX_LEN = 5

class SponsorRegisterRequest(BaseModel):
    username: str
    password: str

class SponsorLoginRequest(BaseModel):
    username: str
    password: str

class SponsorSubmitRequest(BaseModel):
    provider: str
    api_key: str
    brand_name: str
    secret_key: str = ""
    app_id: str = ""

class SponsorVerifyRequest(BaseModel):
    provider: str
    api_key: str

def hash_password(pwd: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 200000)
    return f"{salt}${dk.hex()}"

def verify_password(pwd: str, stored_hash: str) -> bool:
    if '$' not in stored_hash:
        return False
    salt, h = stored_hash.split('$', 1)
    dk = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 200000)
    return dk.hex() == h

def get_user_from_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization[7:]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, expires_at FROM sponsor_sessions WHERE token=?", (token,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user_id, expires_at = row
    if datetime.now().isoformat() > expires_at:
        cursor.execute("DELETE FROM sponsor_sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    conn.close()
    return user_id

@router.post("/register")
async def sponsor_register(req: SponsorRegisterRequest):
    if len(req.username) < 2 or len(req.username) > 20:
        raise HTTPException(status_code=400, detail="用户名2-20个字符")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sponsor_users WHERE username=?", (req.username,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="用户名已被注册")
    pwd_hash = hash_password(req.password)
    cursor.execute("INSERT INTO sponsor_users (username, password_hash) VALUES (?,?)", (req.username, pwd_hash))
    conn.commit()
    user_id = cursor.lastrowid
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(days=SESSION_EXPIRE_DAYS)).isoformat()
    cursor.execute("INSERT INTO sponsor_sessions (user_id, token, expires_at) VALUES (?,?,?)", (user_id, token, expires_at))
    conn.commit()
    conn.close()
    return {"success": True, "token": token, "user_id": user_id, "username": req.username}

@router.post("/login")
async def sponsor_login(req: SponsorLoginRequest):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash FROM sponsor_users WHERE username=?", (req.username,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user_id, pwd_hash = row
    if not verify_password(req.password, pwd_hash):
        conn.close()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(days=SESSION_EXPIRE_DAYS)).isoformat()
    cursor.execute("INSERT INTO sponsor_sessions (user_id, token, expires_at) VALUES (?,?,?)", (user_id, token, expires_at))
    conn.commit()
    conn.close()
    return {"success": True, "token": token, "user_id": user_id, "username": req.username}

@router.post("/verify")
async def sponsor_verify(req: SponsorVerifyRequest):
    provider = req.provider
    if provider not in LLM_PROVIDERS:
        return {"success": False, "error": f"未知厂商: {provider}", "models": []}
    info = LLM_PROVIDERS[provider]
    if info.get("special") in ("baidu", "xfyun"):
        return {"success": True, "warning": f"{info['name']}使用专有API，无法自动验证但接受提交",
                "models": info["models"], "verified": True}
    models_url = info["api_base"].rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(models_url, headers={"Authorization": f"Bearer {req.api_key}"})
        if resp.status_code == 200:
            data = resp.json()
            available = []
            if isinstance(data, dict):
                model_list = data.get("data") or data.get("models") or []
                for m in model_list:
                    if isinstance(m, dict): available.append(m.get("id", ""))
                    elif isinstance(m, str): available.append(m)
            battle_ids = set(m["id"] for m in BATTLE_MODELS if m["provider"] == provider)
            matched = [m for m in battle_ids if m in available]
            return {"success": True, "is_official": True,
                    "models_available": sorted(available),
                    "battle_models": sorted(matched),
                    "all_verified": len(matched) > 0}
        elif resp.status_code in (401, 403):
            return {"success": False, "error": "API Key无效，请检查", "status_code": resp.status_code}
        else:
            return {"success": True, "warning": f"端点返回{resp.status_code}，可能非OpenAI兼容格式，手动审核通过"}
    except Exception as e:
        return {"success": True, "warning": f"无法连接验证端点: {str(e)[:100]}，接受提交，手动审核"}

@router.post("/test")
async def sponsor_test_key(req: SponsorSubmitRequest, user_id: int = Depends(get_user_from_token)):
    """测试 API Key 是否有效（赞助商提交前验证）"""
    if req.provider not in LLM_PROVIDERS:
        return {"success": False, "message": f"未知厂商: {req.provider}"}
    
    provider = LLM_PROVIDERS[req.provider]
    auth_type = provider.get("auth_type", "standard")
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 百度
        if auth_type == "baidu":
            if not req.api_key or not req.secret_key:
                return {"success": False, "message": "百度需要 API Key(AK) 和 Secret Key(SK)"}
            try:
                resp = await client.post(
                    "https://aip.baidubce.com/oauth/2.0/token",
                    data={"grant_type": "client_credentials", "client_id": req.api_key, "client_secret": req.secret_key}
                )
                if resp.status_code == 200 and "access_token" in resp.json():
                    return {"success": True, "message": "百度认证成功 ✓"}
                return {"success": False, "message": f"百度认证失败: {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"百度请求失败: {str(e)}"}
        
        # 华为
        elif auth_type == "huawei":
            if not req.api_key or not req.secret_key:
                return {"success": False, "message": "华为需要 AK 和 SK"}
            try:
                resp = await client.post(
                    "https://iam.cn-north-4.myhuaweicloud.com/v3/auth/tokens",
                    json={
                        "auth": {
                            "identity": {
                                "methods": ["hw_ak_sk"],
                                "hw_ak_sk": {"access": {"key": req.api_key}, "secret": {"key": req.secret_key}}
                            },
                            "scope": {"project": {"name": "cn-north-4"}}
                        }
                    }
                )
                if resp.status_code in (200, 201):
                    return {"success": True, "message": "华为IAM认证成功 ✓"}
                return {"success": False, "message": f"华为IAM认证失败 (HTTP {resp.status_code}): {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"华为IAM请求失败: {str(e)}"}
        
        # 科大讯飞
        elif auth_type == "xfyun":
            if not req.app_id or not req.api_key or not req.secret_key:
                return {"success": False, "message": "科大讯飞需要 APPID、APIKey 和 APISecret"}
            try:
                resp = await client.post(
                    "https://spark-api-open.xf-yun.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {req.api_key}:{req.secret_key}", "Content-Type": "application/json"},
                    json={"model": "generalv3.5", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "科大讯飞认证成功 ✓"}
                return {"success": False, "message": f"科大讯飞认证失败 (HTTP {resp.status_code}): {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"科大讯飞请求失败: {str(e)}"}
        
        # 标准厂商
        else:
            if not req.api_key:
                return {"success": False, "message": "请填写API Key"}
            api_base = provider.get("api_base", "")
            models = provider.get("models", [])
            if not api_base or not models:
                return {"success": False, "message": "该厂商未配置api_base或模型"}
            try:
                resp = await client.post(
                    api_base,
                    headers={"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"},
                    json={"model": models[0], "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "连接成功 ✓"}
                return {"success": False, "message": f"返回错误 (HTTP {resp.status_code}): {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"连接失败: {str(e)}"}

@router.post("/submit")
async def sponsor_submit(req: SponsorSubmitRequest, user_id: int = Depends(get_user_from_token)):
    if len(req.brand_name) > BRAND_MAX_LEN:
        raise HTTPException(status_code=400, detail=f"品牌名最多{BRAND_MAX_LEN}个字")
    if req.provider not in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail="未知厂商")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sponsors WHERE user_id=? AND provider=? AND status='active'",
                   (user_id, req.provider))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="你已有一个活跃赞助给此厂商，无需重复提交")
    
    verify_detail, api_verified, is_valid = "", 1, True
    special = LLM_PROVIDERS[req.provider].get("special")
    if special not in ("baidu", "xfyun"):
        try:
            url = LLM_PROVIDERS[req.provider]["api_base"].rstrip("/") + "/models"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {req.api_key}"})
            if resp.status_code == 200:
                verify_detail = "API验证通过"
            elif resp.status_code in (401, 403):
                is_valid, api_verified = False, 0
                verify_detail = f"API Key无效 (HTTP {resp.status_code})"
            else:
                verify_detail = f"端点返回{resp.status_code}"
        except Exception as e:
            verify_detail = f"验证异常: {str(e)[:100]}"
    
    status = "active" if is_valid else "invalid"
    cursor.execute("UPDATE sponsors SET status='replaced' WHERE user_id=? AND provider=? AND status='active'",
                   (user_id, req.provider))
    cursor.execute("""INSERT INTO sponsors (user_id, provider, api_key, secret_key, app_id, brand_name, status, verify_detail, api_verified)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   (user_id, req.provider, req.api_key, req.secret_key, req.app_id, req.brand_name, status, verify_detail, api_verified))
    conn.commit()
    sid = cursor.lastrowid
    conn.close()
    if not is_valid:
        return {"success": False, "error": f"API Key验证失败: {verify_detail}", "sponsor_id": sid}
    return {"success": True, "message": "赞助提交成功！", "sponsor_id": sid,
            "provider": req.provider, "brand_name": req.brand_name}

@router.get("/me")
async def sponsor_me(user_id: int = Depends(get_user_from_token)):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM sponsor_users WHERE id=?", (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="用户不存在")
    cursor.execute("""SELECT id, provider, brand_name, status, verify_detail, api_verified, created_at
                      FROM sponsors WHERE user_id=? ORDER BY created_at DESC""", (user_id,))
    sponsors = []
    for row in cursor.fetchall():
        pname = LLM_PROVIDERS.get(row[1], {}).get("name", row[1])
        sponsors.append({"id": row[0], "provider": row[1], "provider_name": pname,
                         "brand_name": row[2], "status": row[3], "verify_detail": row[4],
                         "api_verified": bool(row[5]), "created_at": row[6]})
    conn.close()
    return {"user_id": user[0], "username": user[1], "sponsors": sponsors}

@router.get("/active/{provider}")
async def sponsor_active(provider: str):
    if provider not in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail="未知厂商")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""SELECT s.api_key, s.brand_name, s.user_id, u.username
                      FROM sponsors s JOIN sponsor_users u ON s.user_id=u.id
                      WHERE s.provider=? AND s.status='active' AND s.api_verified=1
                      ORDER BY s.created_at ASC LIMIT 1""", (provider,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"active": False, "message": "该厂商暂无活跃赞助商"}
    return {"active": True, "brand_name": row[1], "sponsor_user": row[3]}

@router.get("/providers")
async def sponsor_providers():
    providers = []
    for key, info in LLM_PROVIDERS.items():
        providers.append({"key": key, "name": info["name"], "icon": info.get("icon", ""),
                          "models": info.get("models", []), "color": info.get("color", ""),
                          "docs": info.get("docs", ""), "auth_type": info.get("auth_type", "standard")})
    return {"providers": providers}
