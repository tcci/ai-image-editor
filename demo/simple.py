import logfire

from dataclasses import dataclass


@dataclass(slots=True)
class MyDataClass:
    message: str
    v: int


dc = MyDataClass('hello world', 42)
logfire.info('hello world {value=} {dc=}', value=1234, dc=dc)
