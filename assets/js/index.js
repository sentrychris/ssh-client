import '../css/app.css';
import Alpine from 'alpinejs'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'

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

    const toggleTerminalDisplay = () => {
        document.querySelector('.terminal-wrapper').classList.toggle('is-hidden')
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
                cursorBlink: true,
                fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                fontSize: 13,
                theme: {
                    background: '#09090b',
                    foreground: '#e4e4e7',
                    cursor: '#fafafa',
                    cursorAccent: '#09090b',
                    selectionBackground: 'rgba(255, 255, 255, 0.18)',
                },
            })

            const xtermFitAddon = new FitAddon()
            xterm.loadAddon(xtermFitAddon)

            const fit = () => {
                try { xtermFitAddon.fit() } catch (e) { /* container not ready */ }
            }

            const resizeObserver = new ResizeObserver(fit)

            websocket.onopen = () => {
                this.$refs.container.style.display = 'none'
                toggleTerminalDisplay()
                xterm.open(this.$refs.terminal)

                requestAnimationFrame(() => {
                    fit()
                    resizeObserver.observe(this.$refs.terminal)
                })
            }

            xterm.onData((data) => {
                websocket.send(JSON.stringify({ data }))
            })

            xterm.onResize(({ cols, rows }) => {
                if (websocket.readyState === WebSocket.OPEN) {
                    websocket.send(JSON.stringify({ resize: [cols, rows] }))
                }
            })

            websocket.onmessage = (message) => {
                xterm.write(message.data)
            }

            websocket.onclose = (event) => {
                resizeObserver.disconnect()
                toggleTerminalDisplay()
                xterm.dispose()

                this.$refs.container.style.display = 'block'
                this.setStatus('ok', event.reason || 'Connection closed.')
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
