# Kubernetes with ContainerSSH

[`deploy/kubernetes/`](../deploy/kubernetes/) has an example you apply with `kubectl apply -k`. You reach the agent pod over SSH through [ContainerSSH](https://containerssh.io/v0.6/) v0.6.0, and each login lands in the same tmux session.

- Namespace `agentainer`: a StatefulSet with one pod, `agentainer-0`, and two volumes, `home` (20 Gi) and `workspace` (50 Gi). It meets the [Restricted Pod Security Standard](https://kubernetes.io/docs/concepts/security/pod-security-standards/), mounts no service account token, and keeps sudo off.
- Namespace `containerssh`: the ContainerSSH server in [persistent mode](https://containerssh.io/v0.6/reference/kubernetes/#persistent-mode), and a small Python webhook that checks SSH public keys and tells ContainerSSH which pod to use. A NetworkPolicy lets only ContainerSSH reach the webhook, if your CNI enforces NetworkPolicy.
- The ContainerSSH image on Docker Hub is amd64 only, so its Deployment runs on amd64 nodes. The agentainer pod runs on either architecture.

Not verified: this example has not been deployed to a cluster.

## Contents

- [Install](#install)
- [Logging in](#logging-in)
- [Limits](#limits)
- [SSH port access](#ssh-port-access)
- [Seeding a new home](#seeding-a-new-home)
- [Network policy](#network-policy)
- [Upgrading and removing](#upgrading-and-removing)
- [More than one user](#more-than-one-user)

## Install

Before you apply, set `loadBalancerSourceRanges` in [`containerssh/service.yaml`](../deploy/kubernetes/containerssh/service.yaml) to your client range, block node ports with a firewall (see [SSH port access](#ssh-port-access)), and pin the image in [`agentainer/kustomization.yaml`](../deploy/kubernetes/agentainer/kustomization.yaml) (`images`, `newTag`). The example follows `latest`, which does not exist before the first stable release. Until then, set a published prerelease such as `0.1.0-dev.20261024.1` before applying these manifests ([release policy](versions.md#releases)).

```sh
kubectl apply -f deploy/kubernetes/agentainer/namespace.yaml \
  -f deploy/kubernetes/containerssh/namespace.yaml
kubectl -n agentainer create secret generic agentainer-credentials \
  --from-env-file="$HOME/.config/agentainer/env"
keydir=$(mktemp -d)   # keep the private host key out of the repo
openssl genrsa -out "$keydir/host.key" 4096
kubectl -n containerssh create secret generic containerssh-hostkey --from-file="$keydir/host.key"
rm -r "$keydir"
kubectl -n containerssh create secret generic agentainer-authorized-keys \
  --from-file=authorized_keys="$HOME/.ssh/id_ed25519.pub"
kubectl apply -k deploy/kubernetes
ssh dev@<containerssh service address>
```

- The namespace files carry the `pod-security.kubernetes.io/enforce: restricted` label, so the namespaces enforce the Restricted profile before any pod starts.
- ContainerSSH wants a host key from `openssl genrsa`, not `ssh-keygen` ([installation](https://containerssh.io/v0.6/reference/installation/)). Keep the file name `host.key`: the Deployment mounts only that item of the Secret, and the pod does not start without it.
- The SSH username is `AGENTAINER_USER` in [`auth-webhook/deployment.yaml`](../deploy/kubernetes/auth-webhook/deployment.yaml) (`dev` by default).

## Logging in

- The webhook accepts plain `authorized_keys` lines with these key types: `ssh-ed25519`, `ssh-rsa`, `ecdsa-sha2-nistp256`, `ecdsa-sha2-nistp384`, `ecdsa-sha2-nistp521`, `sk-ssh-ed25519@openssh.com` and `sk-ecdsa-sha2-nistp256@openssh.com`.
- It refuses lines with options such as `from=` or `command=`, because it cannot enforce them, and certificate lines (`*-cert-v01@openssh.com`), which `sshd` trusts only through `cert-authority`. Password logins always fail.
- Each login runs tmux with `TERM=xterm-256color`. ContainerSSH does not pass the client's environment to the pod in this setup, and tmux will not start without `TERM`.
- ContainerSSH sends an SSH keepalive every 30 seconds, so load balancer and NAT idle timers do not drop a quiet session.

The agent pod has startup and readiness probes with a three-minute startup allowance. They execute the image's local health command; legacy images fall back to the active-tools link. These checks do not detect every hung agent. A liveness policy needs a separate responsiveness and recovery contract ([probe semantics](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)).

## Limits

- The webhook gives each request a ten-second deadline for headers and body. It runs at most 16 handler threads and answers further connections with HTTP 503 ([implementation](../deploy/kubernetes/auth-webhook/webhook.py)).
- A cluster has no host folder. Clone repos into `/workspace`. **Work you have not pushed exists only on the workspace volume.**
- sftp and the default `scp` do not work: since OpenSSH 9.0, `scp` uses the SFTP protocol, and the image has no `sftp-server`. `scp -O` (the legacy protocol) and `rsync -e ssh` should work, because ContainerSSH runs those as commands; this is not verified.
- Port forwarding (`ssh -L`, `ssh -R`), socket forwarding and X11 forwarding are off: ContainerSSH disables them by default and the example keeps that.
- The ContainerSSH-to-webhook traffic is plain HTTP inside the cluster. The example has no server-side TLS configuration; adding it requires a server change or TLS-terminating proxy. ContainerSSH's webhook client accepts `cacert`, `cert` and `key` settings for TLS (`config/http.go` in ContainerSSH v0.6.0).
- Resource requests and limits on all three pods are example values.
- To turn sudo on, follow the comment in [`agentainer/statefulset.yaml`](../deploy/kubernetes/agentainer/statefulset.yaml). The capability list there is untested, and the pod then needs the Baseline profile.

## SSH port access

- `loadBalancerSourceRanges` limits only traffic that arrives at the load balancer address. A `LoadBalancer` Service also opens a node port (from 30000-32767 by default) on every node, and kube-proxy does not apply the source ranges to it (`pkg/proxy/iptables/proxier.go` in Kubernetes v1.34.0). Anyone who can reach the node that runs the ContainerSSH pod can reach SSH through that port. Block the node port range from untrusted networks with a firewall in front of the nodes.
- If your load balancer sends traffic straight to pods instead of through node ports, you can set `allocateLoadBalancerNodePorts: false` in the Service, and Kubernetes allocates no node port for it ([Service docs](https://kubernetes.io/docs/concepts/services-networking/service/#load-balancer-nodeport-allocation)). The example does not set it, because a load balancer that routes through node ports stops working without them. Check your provider's documentation before you set it.
- The Service uses `externalTrafficPolicy: Local`, so ContainerSSH sees and logs the client's real address instead of a node address ([Preserving the client source IP](https://kubernetes.io/docs/tasks/access-application-cluster/create-external-load-balancer/#preserving-the-client-source-ip)). The load balancer sends traffic only to nodes that run the ContainerSSH pod.
- To use the commented `NodePort` alternative, change `type` and delete the `loadBalancerSourceRanges` line. The API server rejects a `NodePort` Service that sets it. Restrict access to the node port with a firewall. Connect with `ssh -p <node port>` to the node that runs the ContainerSSH pod; other nodes do not forward the port.

## Seeding a new home

The StatefulSet mounts an optional ConfigMap named `agentainer-seed` at `/etc/agentainer/seed`. When the pod starts, the entrypoint copies `AGENTS.md` and `mcp.json` from it to `~/.agentainer/AGENTS.md` and `~/.agentainer/mcp.json`, but only when that file is missing in the home volume. It never replaces a file that exists, so edits made in the pod survive restarts, and a changed ConfigMap does not reach a home that already has the file. Without the ConfigMap the pod starts as usual and gets the image's default `AGENTS.md`.

```sh
kubectl -n agentainer create configmap agentainer-seed \
  --from-file=AGENTS.md=./AGENTS.md --from-file=mcp.json=./mcp.json
```

Both keys are optional. [Configuration](configuration.md) describes both files; the entrypoint registers the servers in `mcp.json` with each agent. Create the ConfigMap before the first start of a new home volume, or delete the file in the pod and restart the pod to seed it again.

## Network policy

[`agentainer/networkpolicy.yaml`](../deploy/kubernetes/agentainer/networkpolicy.yaml) limits the agent pod's outbound traffic.

- Allowed: DNS on UDP and TCP port 53, and TCP port 443, to every destination, including internal services and any DNS server.
- Not provided: an internet-only allowlist. This is a port restriction. Before you rely on it to isolate hosts or internal services, restrict the DNS selectors and the pod, service and node ranges for your cluster. NetworkPolicy and address translation behavior depend on the CNI ([Kubernetes policy semantics](https://kubernetes.io/docs/concepts/services-networking/network-policies/)).
- Enabling it: the policy is off by default. Add it to that folder's `kustomization.yaml`, with a CNI that enforces NetworkPolicy.

Without it, the agent pod can reach any address, including your cloud provider's instance metadata address (`169.254.169.254`) if the cluster allows it.

## Upgrading and removing

To upgrade, change `newTag` in `agentainer/kustomization.yaml` and run `kubectl apply -k deploy/kubernetes`. After a stable release publishes `latest`, using `newTag: latest` means the manifest does not change, so restart the pod instead: `kubectl -n agentainer rollout restart statefulset agentainer`. The `home` and `workspace` volumes stay.

The StatefulSet keeps the `home` and `workspace` PVCs when it is deleted or scaled down. **`kubectl delete -k deploy/kubernetes` also deletes the `agentainer` namespace, which deletes those PVCs and, with the usual `Delete` reclaim policy, the disks.** To keep your work, delete only the StatefulSet (`kubectl -n agentainer delete statefulset agentainer`), or set the volumes' reclaim policy to `Retain` first.

Every object in `deploy/kubernetes` carries the label `app.kubernetes.io/part-of: agentainer`; the Pods and PVCs created from them do not. To list the labelled objects:

```sh
kubectl get namespace,statefulset,deployment,service,configmap,serviceaccount,role,rolebinding,networkpolicy \
  -A -l app.kubernetes.io/part-of=agentainer
```

## More than one user

The example serves one user. Multi-user support is not built; it would need these changes:

- The webhook's `/config` answer would name a per-user pod such as `agentainer-<user>-0`.
- Each user would get a StatefulSet and volumes, and `authorized_keys` would become a per-user mapping.
- The ContainerSSH Role lists only `agentainer-0` in `resourceNames`. Add each per-user pod to both rules, or give each user a namespace with its own Role and RoleBinding for the ContainerSSH ServiceAccount.

The image stays the same.
