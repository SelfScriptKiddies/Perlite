# How to deploy perlite with auto-sync
## Install python3 and dependencies
```
sudo apt-get install python3 python3-venv
cd deploy
python3 -m venv .venv
. .venv/bin/activate
pip install flask
```

## Clone the storage-repository to `./storage`
```bash
git clone <YOUR-STORAGE-REPO> ./storage
```

## Get github webhook and change service file
Change [wiki-webhook.service](wiki-webhook.service.example) and rename it

## (Optional) Change IP and Port in webhook.py
Default is `127.0.0.1:3011`
and wiki is `127.0.0.1:3010`

## Start service
```
sudo cp wiki-webhook.service /etc/systemd/system/wiki-webhook.service
sudo systemctl daemon-reload
sudo systemctl enable --now wiki-webhook.service
sudo systemctl status wiki-webhook.service
```


