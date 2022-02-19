import Alpine from 'alpinejs'
import {Terminal} from 'xterm'
import {FitAddon} from 'xterm-addon-fit'

window.Alpine = Alpine
window.init = init

function init() {
    const connection = {
        hostname: '',
        port: '22',
        username: '',
        password: '',
        privateKey: null,
    }

    const display = () => {
        document.querySelector('body').classList.toggle('xterm_display')
        document.querySelector('.xterm-viewport').classList.toggle('xterm_display')
    }

    return {
        connection,

        state: {
            status: '',
            message: '',
            loading: null,
        },

        terminal: null,

        async initReactiveProperties() {
            this.loading = false
        },

        async connect() {
            this.loading = true

            const url = '/'
            const method = 'POST'
            const body = JSON.stringify(connection)

            if (connection.privateKey && connection.privateKey.size > 16384) {
                this.status = 'Key size exceeds maximum value.'
            }

            try {
                const response = await fetch(url, {
                    mode: 'cors',
                    credentials: 'same-origin',
                    method,
                    body
                })

                const payload = await response.json()
                await this.process(payload)
            } catch (err) {
                console.log(err)
            }
        },

        async process(response) {
            if (response.message) {
                this.status.message = response.message

                setTimeout(function () {
                    this.loading = false
                }, 300)

                return
            }

            const wsUrl = window.location.href.replace('http', 'ws')
            const join = (wsUrl[wsUrl.length - 1] === '/' ? '' : '/')
            const url = wsUrl + join + 'ws?id=' + response.id

            const websocket = new WebSocket(url)

            const xterm = new Terminal({
                cursorBlink: true
            })

            const xdisplay = new FitAddon()
            xterm.loadAddon(xdisplay)

            websocket.onopen = () => {
                this.$refs.container.style.display = 'none'
                xterm.open(this.$refs.terminal)

                display()

                xdisplay.fit()
            }

            xterm.onData((data) => {
                websocket.send(data)
            })

            websocket.onmessage = (message) => {
                xterm.write(message.data)
            }

            websocket.onclose = (event) => {
                display()
                xterm.dispose()

                this.$refs.container.style.display = 'block'
                this.status.message = event.reason
            };

            websocket.onerror = event => {
                console.log(event)
            }
        }
    }
}

Alpine.start()
