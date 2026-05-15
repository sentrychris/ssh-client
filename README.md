# Web SSH client.

A small and simple web-based SSH client. Built with [Paramiko](https://www.paramiko.org/), [Tornado](https://www.tornadoweb.org/en/stable/), [XtermJS](https://xtermjs.org/) and [Alpine.js](https://alpinejs.dev/)

## Installation

Requires Python >= 3.10. Uses the stdlib `venv` module and `pip`; no extra
tooling needed.

Clone the repository and create your venv:
```sh
$ git clone https://github.com/sentrychris/ssh-client.git
$ cd ssh-client
$ python -m venv .venv
```

Install Python dependencies:
```sh
$ pip install .
```

Install NPM dependencies:
```sh
$ npm install
```

Build:
```sh
$ npm run build
```

Run:
```sh
$ python ssh.py --address=0.0.0.0 --port=4500
```


