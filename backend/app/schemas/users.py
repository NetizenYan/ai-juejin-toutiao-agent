from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


class UserRequest(BaseModel):
    """Login. Only basic bounds, so accounts created before the register rules still sign in."""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def _strip_username(cls, value: str) -> str:
        return value.strip()


class RegisterRequest(UserRequest):
    """Register. user.username is VARCHAR(50): longer names used to fail in the database with a 500.
    The password minimum matches UserChangePasswordRequest."""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)

    @field_validator("username")
    @classmethod
    def _username_has_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("用户名至少 3 个字符")
        return value


# user_info 对应的类：基础类 + Info 类（id、用户名）
class UserInfoBase(BaseModel):
    """
    用户信息基础数据模型
    """
    nickname: Optional[str] = Field(None, max_length=50, description="昵称")
    avatar: Optional[str] = Field(None, max_length=255, description="头像URL")
    gender: Optional[str] = Field(None, max_length=10, description="性别")
    bio: Optional[str] = Field(None, max_length=500, description="个人简介")


class UserInfoResponse(UserInfoBase):
    id: int
    username: str

    # 模型类配置
    model_config = ConfigDict(
        from_attributes=True  # 允许从 ORM 对象属性中取值
    )


# data 数据类型
class UserAuthResponse(BaseModel):
    token: str
    user_info: UserInfoResponse = Field(..., alias="userInfo")

    # 模型类配置
    model_config = ConfigDict(
        populate_by_name=True,  # alias / 字段名兼容
        from_attributes=True  # 允许从 ORM 对象属性中取值
    )


# 更新用户信息的模型类
class UserUpdateRequest(BaseModel):
    nickname: Optional[str] = Field(None, max_length=50)
    avatar: Optional[str] = Field(None, max_length=255)
    # 与 user.gender 的数据库 ENUM 一致，非法值在校验阶段返回 422，而不是写库时报 500
    gender: Optional[Literal["male", "female", "unknown"]] = None
    bio: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=20)


class UserChangePasswordRequest(BaseModel):
    old_password: str = Field(..., alias="oldPassword", description="旧密码")
    new_password: str = Field(..., min_length=6, alias="newPassword", description="新密码")
