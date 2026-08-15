# Dokku Deployment

Install [Podman](https://podman.io) and verify it:

```
sudo apt install -y podman
sudo podman run hello-world
```

Enable the Podman systemd socket and verify it:

```
sudo systemctl enable --now podman.socket
systemctl status podman.socket --no-pager
```

Override the socket path by running `sudo systemctl edit podman.socket` and editing the contents to:

```
[Socket]
ListenStream=
ListenStream=/run/podman.sock
SocketMode=0666
```

Reboot the machine.

Quick test (should display full Podman information and not throw any errors):

```
CONTAINER_HOST="unix:///run/podman.sock" podman --remote info
```

Run the test again to verify that the Podman socket permissions persist after reboot:

Another test:

```
CONTAINER_HOST="unix:///run/podman.sock" podman --remote run hello-world
```

Install and configure [Tailscale](https://tailscale.com) on the host machine:

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Verify that the machine appears on the [Tailscale admin console page](https://login.tailscale.com/admin/machines).

Install Dokku per [the official guide](https://dokku.com/docs/getting-started/installation):

```
wget -NP . https://dokku.com/install/v0.37.2/bootstrap.sh
sudo DOKKU_TAG=v0.37.2 bash bootstrap.sh
```

Add at least one SSH key for manual deployment.

Create the app:

```
dokku apps:create podmanfleet
dokku ports:add podmanfleet http:80:8400
dokku config:set podmanfleet CONTAINER_HOST="unix:///run/podman.sock"
dokku docker-options:add podmanfleet deploy "--cap-add=NET_ADMIN"
dokku docker-options:add podmanfleet deploy "--cap-add=NET_RAW"
dokku docker-options:add podmanfleet deploy "--device=/dev/net/tun:/dev/net/tun"
dokku docker-options:add podmanfleet deploy,run "-v /run/podman.sock:/run/podman.sock"
```

Set the domain (optional):

```
dokku domains:set podmanfleet podmanfleet.example.com
```

Then deploy Podman Fleet manually to this Dokku machine.
