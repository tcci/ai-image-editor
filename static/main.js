function dndListeners(dnd_el) {
  if (dnd_el) {
    dnd_el.addEventListener('drop', dnd)
    dnd_el.addEventListener('dragover', (ev) => {
      ev.preventDefault()
      dnd_el.classList.add('dragover')
    })
    dnd_el.addEventListener('dragleave', (ev) => {
      ev.preventDefault()
      dnd_el.classList.remove('dragover')
    })
  }
}
const getByID = id => document.getElementById(id)
dndListeners(getByID('dnd'))

let global_image;

function dnd(event) {
  event.preventDefault()
  hideError()
  event.target.classList.remove('dragover')

  let files
  if (event.dataTransfer.items) {
    files = [...event.dataTransfer.items].map((item) => {
      if (item.kind === 'file') {
        return item.getAsFile()
      }
    }).filter(Boolean)
  } else {
    files = [...event.dataTransfer.files]
  }

  const image = files.find((file) => file.type.startsWith('image/'))
  if (image) {
    const body = new FormData()
    body.append('image', image)
    fetch('/new-image/', {method: 'POST', body})
      .then((r) => {
        if (r.ok) {
          r.json().then((new_image) => {
            new_image.image_url = URL.createObjectURL(image)
            global_image = {data: image, msgs: [new_image]}
            render()
          })
        } else {
          showError(`Server returned ${r.status}`)
        }
      })
      .catch((e) => showError(`Upload failed: ${e}`))
  } else {
    showError('Upload must be an image')
  }
}

function render () {
  console.debug('global_image:', global_image)

  const {data, msgs} = global_image
  const messages = msgs.map((m) => `<div class="message">${renderMsg(m)}</div>`).join('\n')

  const metadata = msgs[msgs.length - 1]
  let dynamic_el = getByID('dynamic')
  dynamic_el.innerHTML = `
<div class="image-area">
  <img class="main-img" src="${URL.createObjectURL(data)}" alt="${metadata.filename}" />
  <div class="label">${metadata.filename} ${metadata.width}x${metadata.height}</div>
</div>
<div class="conversation">
  ${messages}
  <div class="message">
    <h3>User</h3>
    <textarea class="input" placeholder="Type your message here"></textarea>
    <div class="flex-justify-right">
      <button class="send">Send</button>
    </div>
  </div>
</div>
  `
  const textarea_el = dynamic_el.querySelector('textarea')
  textarea_el.focus()
  // todo on command+enter send
  dynamic_el.querySelector('button.send').addEventListener('click', send)
}

function send() {
  const textarea_el = getByID('dynamic').querySelector('textarea')
  textarea_el.disabled = true

  const {data, msgs} = global_image
  const {session_id} = msgs[msgs.length - 1]
  console.log('send:', textarea_el.value)

  const body = new FormData()
  body.append('prompt', textarea_el.value)
  body.append('session_id', session_id)
  body.append('image', data)

  fetch('/prompt/', {method: 'POST', body})
    .then((r) => {
      if (r.ok) {
        r.json().then(data => {
          console.log('response:', data)
          // global_image = {data: image, metadata, msgs: [metadata]}
          // render()
        })
      } else {
        showError(`Server returned ${r.status}`)
      }
    })
    .catch((e) => showError(`Upload failed: ${e}`))
}

function renderMsg(msg) {
  if (msg.type === 'new-image') {
    return `
<h3>System</h3>
<p>Image details:</p>
<dl>
  <dt>Filename:</dt><dd>${msg.filename}</dd>
  <dt>Size:</dt><dd>${msg.width}x${msg.height}</dd>
  <dt>Image Mode:</dt><dd>${msg.mode}</dd>
</dl>`
  }
}

const error_el = getByID('error')

function showError(message) {
  error_el.innerText = message
  error_el.classList.remove('hidden')
}

function hideError() {
  error_el.classList.add('hidden')
}
