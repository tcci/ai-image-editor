from __future__ import annotations as _annotations

import asyncio
import subprocess
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import time
from pathlib import Path
from typing import Annotated, Literal, ParamSpec, TypeVar, Callable

from fastapi import FastAPI, Depends, Request, UploadFile, Form, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel
from PIL.Image import Image, open as open_image

from .sessions import Session, sessions
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


P = ParamSpec('P')
R = TypeVar('R')


@dataclass(slots=True)
class Executor:
    request: Request

    async def run(self, func: Callable[P, R], *args: P.args) -> R:
        loop = asyncio.get_running_loop()
        executor = self.request.app.state.executor
        return await loop.run_in_executor(executor, func, *args)


def get_executor(request: Request) -> Executor:
    return Executor(request)


last_build: tuple[int, bytes] | None = None


def build_main_js() -> bytes:
    main_ts = THIS_DIR / 'main.ts'
    global last_build
    last_mod = main_ts.stat().st_mtime_ns
    if last_build is not None:
        ts, content = last_build
        if last_mod <= ts:
            return content

    print('building main.js')
    esbuild = THIS_DIR.parent / 'node_modules' / '.bin' / 'esbuild'
    p = subprocess.run([esbuild, str(main_ts), '--bundle'], stdout=subprocess.PIPE, check=True, text=False)
    last_build = last_mod, p.stdout
    return p.stdout


@app.get('/main.js')
async def main_js(executor: Annotated[Executor, Depends(get_executor)]) -> Response:
    content = await executor.run(build_main_js)
    return Response(content=content, media_type='application/javascript')


tmp_files_dir = 'tmp_images'


def load_image(image_file: UploadFile | None = None, image_url: Annotated[str | None, Form()] = None) -> Image:
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
    executor: Annotated[Executor, Depends(get_executor)],
    pil_image: Annotated[Image, Depends(load_image)],
    session: Annotated[Session, Depends(sessions.get)],
    prompt: Annotated[str, Form()],
) -> PromptResponse:
    result = await executor.run(transform_image, pil_image, prompt)
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
                url=f'/static/{temp_path}', width=width, height=height, transformation=result.transformation
            )
        )
