import Alpine from 'alpinejs'
import { Terminal } from 'xterm'
import { FitAddon } from 'xterm-addon-fit'

window.Alpine = Alpine
window.connectionManager = connectionManager

function connectionManager() {
    const connection = {
        hostname: '',
        port: '22',
        username: '',
        password: '',
        privateKey: null,
    }

    const displayTerminal = () => {
        document.querySelector('body').classList.toggle('xterm_display')
        document.querySelector('.terminal-wrapper').classList.toggle('d-none')
        document.querySelector('.xterm-viewport').classList.toggle('xterm_display')
    }

    return {
        connection,

        state: {
            status: '',
            message: '',
            loading: null,
        },

        async initialize() {
            this.setStatus('ok', 'Requesting new connection.', true)

            const url = '/'
            const method = 'POST'
            const body = JSON.stringify(connection)

            if (connection.privateKey && connection.privateKey.size > 16384) {
                this.setStatus('error', 'Your key size exceeds the maximum limit.')
            }

            try {
                const response = await fetch(url, {
                    mode: 'cors',
                    credentials: 'same-origin',
                    method,
                    body
                })

                const worker = await response.json()
                await this.connect(worker)
            } catch (err) {
                console.log(err)
            }
        },

        async connect(worker) {
            if (!worker.id) {
                this.setStatus('ok', worker.status)
                return
            }

            this.setStatus('ok', 'Starting websocket connection.')

            const wsUrl = window.location.href.replace('http', 'ws')
            const join = (wsUrl[wsUrl.length - 1] === '/' ? '' : '/')
            const url = wsUrl + join + 'ws?id=' + worker.id

            const websocket = new WebSocket(url)

            const xterm = new Terminal({
                cursorBlink: true
            })

            const xtermFitAddon = new FitAddon()
            xterm.loadAddon(xtermFitAddon)

            websocket.onopen = () => {
                this.$refs.container.style.display = 'none'
                xterm.open(this.$refs.terminal)

                displayTerminal()

                setTimeout(() => {
                    xtermFitAddon.fit()
                }, 50);

                window.addEventListener('resize', () => xtermFitAddon.fit())
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
                this.setStatus('ok', event.reason)
            };

            websocket.onerror = event => {
                console.log(event)
            }
        },

        setStatus(status, message, loading = false) {
            this.state.status = status
            this.state.message = message
            this.state.loading = loading
        }
    }
}

Alpine.start()
