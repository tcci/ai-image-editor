from __future__ import annotations as _annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from time import time
from uuid import uuid4
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Depends, Request, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel
from PIL.Image import Image, open as open_image

import logfire

from .transform import transform_image, Refusal, ImageTransform, ImageTransformDef


@asynccontextmanager
async def lifespan(app: FastAPI):
    with ProcessPoolExecutor(max_workers=8) as executor:
        app.state.executor = executor
        yield


app = FastAPI(lifespan=lifespan)

THIS_DIR = Path(__file__).parent
static_dir = THIS_DIR.parent / 'static'
app.mount('/static', StaticFiles(directory=static_dir), name='static')


@app.get('/', response_class=HTMLResponse)
@app.head('/', include_in_schema=False)
async def index():
    return FileResponse(THIS_DIR / 'index.html')


@app.get('/favicon.ico')
async def favicon():
    return FileResponse(static_dir / 'favicon.ico')


@dataclass(slots=True)
class Session:
    session_id: str
    width: int
    height: int
    mode: str
    # conversation: list[dict[str, str]] = field(default_factory=list)
    last_active: datetime = field(default_factory=datetime.utcnow)
    tmp_images: list[Path] = field(default_factory=list)


class Sessions:
    _max_age = timedelta(minutes=5)

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def add_new(self, width: int, height: int, mode: str) -> Session:
        session_id = uuid4().hex
        session = Session(session_id=session_id, width=width, height=height, mode=mode)
        self._sessions[session_id] = session
        return session

    def remove_old_sessions(self) -> None:
        now = datetime.utcnow()
        to_remove: list[Session] = []

        for session in self._sessions.values():
            if now - session.last_active > self._max_age:
                to_remove.append(session)

        for session in to_remove:
            for path in session.tmp_images:
                path.unlink(missing_ok=True)
            del self._sessions[session.session_id]

    async def get(self, session_id: Annotated[str, Form()]) -> Session:
        try:
            session = self._sessions[session_id]
        except KeyError:
            raise HTTPException(status_code=404, detail='Image not found')
        else:
            session.last_active = datetime.utcnow()
            self.remove_old_sessions()
            return session


sessions = Sessions()
tmp_files_dir = 'tmp_images'


def load_image(image_file: UploadFile | None = None, image_url: str | None = None) -> Image:
    if image_file is not None:
        try:
            img = open_image(image_file.file)
        except OSError:
            raise HTTPException(status_code=400, detail='Invalid image')
        return img
    elif image_url is not None:
        path = static_dir / tmp_files_dir / Path(image_url).name
        if not path.is_file():
            raise HTTPException(status_code=404, detail='Image not found')
        try:
            img = open_image(path)
        except OSError:
            raise HTTPException(status_code=400, detail='Invalid image')
        return img
    else:
        raise HTTPException(status_code=400, detail='No image provided')


class NewImageResponse(BaseModel):
    """
    WARNING: should match `NewImageResponse` in typescript
    """
    type: Literal['new-image'] = 'new-image'
    session_id: str
    filename: str
    width: int
    height: int
    format: str
    mode: str


@app.post('/new-image/')
async def new_image(image_file: UploadFile, pil_image: Annotated[Image, Depends(load_image)]) -> NewImageResponse:
    sessions.remove_old_sessions()
    width, height = pil_image.size
    session = sessions.add_new(width, height, pil_image.mode)
    return NewImageResponse(
        session_id=session.session_id,
        filename=image_file.filename,
        width=width,
        height=height,
        format=pil_image.format,
        mode=pil_image.mode,
    )


class TransformationSuccess(BaseModel):
    url: str
    width: int
    height: int
    transformation: ImageTransformDef


class PromptResponse(BaseModel):
    """
    WARNING: should match `PromptResponse` in typescript
    """
    type: Literal['prompt-response'] = 'prompt-response'
    result: str | TransformationSuccess


@app.post('/prompt/')
async def prompt_function(
    request: Request,
    pil_image: Annotated[Image, Depends(load_image)],
    session: Annotated[Session, Depends(sessions.get)],
    prompt: Annotated[str, Form()]
) -> PromptResponse:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(request.app.state.executor, transform_image, pil_image, prompt)
    if isinstance(result, Refusal):
        return PromptResponse(result=result.message)
    else:
        assert isinstance(result, ImageTransform), f'Unexpected result type {type(result)}'
        img_format = result.transformation.save_as or pil_image.format
        temp_path = Path(tmp_files_dir) / f'{session.session_id}-{time()}.{img_format.lower()}'
        save_path = static_dir / temp_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = result.image.size
        result.image.save(save_path, img_format)
        return PromptResponse(
            result=TransformationSuccess(
                url=f'/static/{temp_path}',
                width=width,
                height=height,
                transformation=result.transformation,
            )
        )
