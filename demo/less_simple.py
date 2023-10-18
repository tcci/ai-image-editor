import logfire

from dataclasses import dataclass


@dataclass(slots=True)
class MyDataClass:
    message: str
    v: int


dc = MyDataClass('hello world', 42)

logfire.info('hello world {dc=} v={value}', dc=dc, value=1234)


from pydantic import BaseModel


class MyModel(BaseModel):
    message: str
    v: int


m = MyModel(message='hello', v=42)
