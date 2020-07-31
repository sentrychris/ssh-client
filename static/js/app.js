import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import axios from 'axios';

const container = document.querySelector('.container');

let btn = document.querySelector('.btn-primary');
let form = document.getElementById('connect');
let status = document.getElementById('status');

const rpsh = {};
rpsh.connect = () => {
    form.addEventListener('submit', event => {
        event.preventDefault();
        let url = form.getAttribute('action'),
            type = form.getAttribute('type'),
            data = new FormData(form);

        let private_key = data.get('private_key');
        if (private_key && private_key.size > 16384) {
            status.innerText = 'Key size exceeds maximum value.';
        }

        status.innerText = '';
        btn.setAttribute('disabled', true);

        axios({
            method: type,
            url: url,
            data: data
        }).then(response => {
            process(response.data);
        })
    });
}

const process = msg => {
    if (msg.status) {
        status.innerText = msg.status;
        setTimeout(function () {
            btn.setAttribute('disabled', false);
        }, 3000);

        return;
    }

    const ws_url = window.location.href.replace('http', 'ws');
    const join = (ws_url[ws_url.length - 1] === '/' ? '' : '/');
    const url = ws_url + join + 'ws?id=' + msg.id;
    const websocket = new WebSocket(url);

    const terminal = document.getElementById('terminal');
    const xterm = new Terminal({ cursorBlink: true });
    const fda = new FitAddon();
    xterm.loadAddon(fda);

    xterm.onData(data => {
        websocket.send(data)
    });

    websocket.onopen = () => {
        container.style.display = 'none';

        xterm.open(terminal);
        fda.fit();
    };

    websocket.onmessage = msg => {
        xterm.write(msg.data);
    }

    websocket.onclose = event => {
        xterm.dispose();
        container.style.display = 'initial';
        status.innerText = event.reason;
        btn.setAttribute('disabled', false);
    };

    websocket.onerror = event => {
        console.log(event);
    }
}

export default rpsh;