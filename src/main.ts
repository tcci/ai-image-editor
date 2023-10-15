interface ImageInfo {
  data: string | File
  filename: string
  width: number
  height: number
  // slightly where to put it here, but it's convenient
  session_id: string
}

interface SystemMessage {
  type: 'system'
  text: string
  attributes?: { [key: string]: string | number }
}

interface UserMessage {
  type: 'user'
  prompt: string
}

interface NewImageResponse {
  type: 'new-image'
  session_id: string
  filename: string
  width: number
  height: number
  format: string
  mode: string
}

type Json = string | number | boolean | null | Json[] | { [key: string]: Json }

interface PromptResponse {
  type: 'prompt-response'
  result:
    | string
    | {
        url: string
        width: number
        height: number
        transformation: { [key: string]: Json }
      }
}

const getByID = (id: string): HTMLElement => {
  const el = document.getElementById(id)
  if (!el) {
    throw new Error(`no element with id ${id}`)
  }
  return el
}

function showError(message: string) {
  const error_el = getByID('error')
  error_el.innerText = message
  error_el.classList.remove('hidden')
}

function hideError() {
  const error_el = getByID('error')
  error_el.classList.add('hidden')
}

class ImageEditor {
  readonly dynamic_el: HTMLElement
  image: ImageInfo | null = null
  messages: (SystemMessage | UserMessage)[] = []

  constructor() {
    this.dynamic_el = getByID('dynamic')
    this.render()
  }

  onDrop(event: DragEvent, dnd_el: HTMLElement) {
    event.preventDefault()
    hideError()
    dnd_el.classList.remove('dragover')

    if (!event.dataTransfer) {
      return
    }

    const files: File[] = Array.from(event.dataTransfer.files)
    const image = files.find((file) => file.type.startsWith('image/'))
    if (image) {
      const body = new FormData()
      body.append('image_file', image)
      post('/new-image/', body).then((new_image: NewImageResponse) => {
        this.image = {
          data: image,
          filename: image.name,
          width: new_image.width,
          height: new_image.height,
          session_id: new_image.session_id,
        }
        this.messages.push({
          type: 'system',
          text: 'Image Uploaded',
          attributes: {
            width: new_image.width,
            height: new_image.height,
            format: new_image.format,
            mode: new_image.mode,
          },
        })
        this.render()
      })
    } else {
      showError('Upload must be an image')
    }
  }

  render(loading: boolean = false) {
    const { image } = this
    if (!image) {
      this.renderHtml(`
<div class="dnd-container">
  <div id="dnd">drag and drop an image here to begin.</div>
  <div id="error" class="hidden"></div>
</div>`)
      this.addDndListeners()
      return
    }

    const messages = this.messages
      .map((m) => `<div class="message">${renderMsg(m)}</div>`)
      .join('\n')

    const src =
      typeof image.data === 'string'
        ? image.data
        : URL.createObjectURL(image.data)
    this.renderHtml(`
<div class="image-area">
  <div class="checkerboard">
    <img class="main-img" src="${src}" alt="${image.filename}" />
  </div>
  <div class="label">${image.filename} ${image.width}x${image.height}</div>
</div>
<div class="conversation">
  <div id="error" class="hidden"></div>
  ${messages}
  ${ImageEditor.renderFinal(loading)}
</div>
`)
    const button = this.dynamic_el.querySelector('button.send')
    if (button) {
      button.addEventListener('click', () => this.send())
      const textarea_el = this.dynamic_el.querySelector('textarea')!
      // todo on command+enter send
      textarea_el.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) {
          this.send()
        }
      })
      textarea_el.focus()
    }
  }

  addDndListeners() {
    const dnd_el = getByID('dnd')
    dnd_el.addEventListener('drop', (ev) => this.onDrop(ev, dnd_el))
    dnd_el.addEventListener('dragover', (ev) => {
      ev.preventDefault()
      dnd_el.classList.add('dragover')
    })
    dnd_el.addEventListener('dragleave', (ev) => {
      ev.preventDefault()
      dnd_el.classList.remove('dragover')
    })
  }

  static renderFinal(loading: boolean): string {
    if (loading) {
      return `<div class="message">
  <div class="lds-ellipsis"><div></div><div></div><div></div><div></div></div>
</div>`
    } else {
      return `
<div class="message">
  <h3>User</h3>
  <textarea class="input" placeholder="Describe how you would like to transform the image..."></textarea>
  <div class="flex-justify-right">
    <button class="send">Send</button>
  </div>
</div>`
    }
  }

  send() {
    const textarea_el = this.dynamic_el.querySelector('textarea')!
    const text = textarea_el.value.trim()
    this.messages.push({ type: 'user', prompt: text })
    this.render(true)

    const image = this.image!
    const body = new FormData()
    body.append('prompt', text)
    body.append('session_id', image.session_id)
    if (typeof image.data === 'string') {
      body.append('image_url', image.data)
    } else {
      body.append('image_file', image.data)
    }
    post('/prompt/', body)
      .then((data: PromptResponse) => {
        if (typeof data.result === 'string') {
          this.messages.push({
            type: 'system',
            text: data.result,
          })
        } else {
          const { url, width, height, transformation } = data.result
          this.messages.push({
            type: 'system',
            text: 'Image Transformed',
            attributes: convertToAttributes(transformation),
          })
          image.data = url
          image.width = width
          image.height = height
        }
        this.render()
      })
      .catch((e) => {
        this.messages.push({
          type: 'system',
          text: `Error: ${e}`,
        })
        this.render()
      })
  }

  renderHtml(html: string) {
    this.dynamic_el.innerHTML = html
  }
}

;(window as any).image_editor = new ImageEditor()

function renderMsg(msg: SystemMessage | UserMessage): string {
  if (msg.type === 'system') {
    let attrs = ''
    if (msg.attributes) {
      attrs = Object.entries(msg.attributes)
        .map(([k, v]) => `<dt>${title(k)}:</dt><dd>${v}</dd>`)
        .join(' ')
      attrs = `<dl>${attrs}</dl>`
    }
    return `
<h3>System</h3>
<p>${msg.text}</p>
${attrs}`
  } else {
    // user message
    return `
<h3>User</h3>
<p>${msg.prompt}</p>`
  }
}

function convertToAttributes(obj: {
  [key: string]: Json
}): Record<string, string> {
  const attrs: Record<string, string> = {}
  for (const [k, v] of Object.entries(obj)) {
    if (
      typeof v === 'string' ||
      typeof v === 'number' ||
      typeof v === 'boolean'
    ) {
      attrs[k] = v.toString()
    } else if (Array.isArray(v)) {
      attrs[k] = v.map(convertJsonValue).join(', ')
    } else if (v != null) {
      for (const [k2, v2] of Object.entries(v)) {
        attrs[`${k}.${k2}`] = convertJsonValue(v2)
      }
    }
  }
  return attrs
}

function convertJsonValue(v: Json): string {
  if (
    typeof v === 'string' ||
    typeof v === 'number' ||
    typeof v === 'boolean'
  ) {
    return v.toString()
  } else if (v === null) {
    return 'null'
  } else if (Array.isArray(v)) {
    return v.map(convertJsonValue).join(', ')
  } else {
    return JSON.stringify(v)
  }
}

const title = (s: string) =>
  s.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())

async function post(url: string, body: FormData): Promise<any> {
  let r
  try {
    r = await fetch(url, { method: 'POST', body })
  } catch (e) {
    showError(`POST Error: ${e}`)
    throw e
  }
  if (r.ok) {
    return await r.json()
  } else {
    showError(`${r.status} server response`)
    throw new Error(`server responded with ${r.status}`)
  }
}
