import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import axios from 'axios';

const container = document.querySelector('.container');

let btn = document.querySelector('.btn-success');
let form = document.getElementById('connect');
let status = document.getElementById('status');
let loading = document.querySelector('.loading');

const tornamiko = {};
tornamiko.connect = () => {
    form.addEventListener('submit', event => {
        event.preventDefault();

        loading.style.display = 'inline';

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
            console.log(response);
            loading.style.display = 'none';
            process(response.data);
        }).catch(error => {
            console.log(error);
        });
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
    const xdisplay = new FitAddon();
    xterm.loadAddon(xdisplay);

    xterm.onData(data => {
        websocket.send(data)
    });

    websocket.onopen = () => {
        container.style.display = 'none';
        xterm.open(terminal);

        toggle_display();

        xdisplay.fit();
    };

    websocket.onmessage = msg => {
        xterm.write(msg.data);
    }

    websocket.onclose = event => {
        console.log(event);
        toggle_display();
        xterm.dispose();
        container.style.display = 'block';
        status.innerText = event.reason;
        btn.removeAttribute('disabled');
    };

    websocket.onerror = event => {
        console.log(event);
    }
}

let toggle_display = () => {
    document.querySelector('body').classList.toggle('xterm_display');
    document.querySelector('.xterm-viewport').classList.toggle('xterm_display');
};

export default tornamiko;