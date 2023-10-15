import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import openai
from annotated_types import Ge, Le
from PIL.Image import Image, open as open_image, new as new_image
from PIL import ImageEnhance as image_enhance

from pydantic import BaseModel, Field

import logfire


class ScaleImage(BaseModel):
    width: int
    height: int


class CropImage(BaseModel):
    width: int
    height: int
    x: int
    y: int


class ImageTransformDef(BaseModel):
    resize: CropImage | ScaleImage | None = None
    make_grayscale: bool | None = None
    replace_trans_color: str | None = Field(None, description='Replace transparency with this color')
    make_trans_threshold: Annotated[int, Ge(0), Le(255)] = Field(
        None, description='Make the image transparent using this threshhold'
    )
    brightness_adjust: Annotated[float, Ge(0), Le(100)] | None = Field(
        None, description='Brightness adjustment percentage'
    )
    contrast_adjust: Annotated[float, Ge(0), Le(100)] | None = Field(None, description='Contrast adjustment percentage')
    save_as: Literal['PNG', 'JPG', 'BMP'] = None


@dataclass(slots=True)
class Refusal:
    message: str


@dataclass(slots=True)
class ImageTransform:
    image: Image
    transformation: ImageTransformDef


@logfire.instrument('transform_image {img=} {user_prompt=!r}')
def transform_image(img: Image, user_prompt: str) -> Refusal | ImageTransform:
    width, height = img.size
    logfire.info('image size is {width}x{height}', width=width, height=height)
    messages = [
        {'role': 'system', 'content': setup},
        {'role': 'system', 'content': f'image current size is {width}x{height}'},
        {'role': 'user', 'content': user_prompt},
    ]

    with logfire.span('calling OpenAI'):
        response = openai.ChatCompletion.create(model='gpt-4', messages=messages, functions=functions)
        tokens_used = response['usage']['prompt_tokens']
        logfire.info('got response {tokens_used=}', tokens_used=tokens_used, user_prompt=user_prompt, response=response)

    response_choice = response['choices'][0]
    finish_reason = response_choice['finish_reason']
    if finish_reason == 'stop':
        msg = response_choice['message']['content']
        logfire.warning('OpenAI refused to resize the image: {msg}', msg=msg)
        return Refusal(msg)
    else:
        assert finish_reason == 'function_call'
        message = response_choice['message']
        arguments_json: str = message['function_call']['arguments']
        # model_validate_json currently doesn't instrument
        model = ImageTransformDef.model_validate(json.loads(arguments_json))

    if model is not None:
        with logfire.span('transforming image'):
            match model.resize:
                case ScaleImage(width=width, height=height):
                    img = img.resize((width, height))
                case CropImage(width=width, height=height, x=x, y=y):
                    box = (x, y, x + width, y + height)
                    img = img.crop(box)

            if model.make_grayscale:
                img = img.convert('L')

            if model.replace_trans_color is not None:
                new_img = new_image('RGBA', img.size, model.replace_trans_color)
                new_img.paste(img, mask=img)
                img = new_img

            if model.make_trans_threshold is not None:
                img = img.convert('RGBA')

                data = list(img.getdata())

                for index, item in enumerate(data):
                    if item[0] + item[1] + item[2] > model.make_trans_threshold * 3:
                        data[index] = (255, 255, 255, 0)

                img.putdata(data)

            if (b := model.brightness_adjust) is not None:
                img = image_enhance.Brightness(img).enhance(1 + b / 100)
            if (c := model.contrast_adjust) is not None:
                img = image_enhance.Contrast(img).enhance(1 + c / 100)
            return ImageTransform(img, model)


functions = [
    {
        'name': 'resize_image',
        'description': 'Defines transformations to an image',
        'parameters': ImageTransformDef.model_json_schema(),
    }
]
setup = """
Help the use by defining how an image should be transformed based on the user's input.

If you unable to interpret the user's input, please explain who, do NOT respond with code examples.

If possible, call the function rather than making recommendations to the user.

DO NOT use markdown formatting, just plain text.

DO NOT make function call suggestions.
"""


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('image_path', type=Path)
    # example prompts:
    # * make the image square by cropping it and increase the brightness by 10%
    # * crop the image to be square, centered
    # * crop the image to be square, left offset 0
    parser.add_argument('user_prompt', type=str)

    args = parser.parse_args()

    with logfire.span('loading image'):
        img_ = open_image(args.image_path)
    try:
        result = transform_image(img_, args.user_prompt)
        if isinstance(result, ImageTransform):
            new_path = args.image_path.with_stem(f'{args.image_path.stem}-transformed')
            if (save_as := result.transformation.save_as) is not None:
                new_path = new_path.with_suffix(f'.{save_as}')
            result.image.save(new_path)
    finally:
        img_.close()
