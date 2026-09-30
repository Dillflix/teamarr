<p align="center">
  <img src="docs/assets/images/teamarr_electric_blue.png" alt="Teamarr — Sports Channel Management for Dispatcharr" width="420">
</p>

<p align="center"><strong>Sports Channel Management for <a href="https://github.com/Dispatcharr/Dispatcharr">Dispatcharr</a></strong></p>

## Quick Start — Dillflix fork

Build and launch this fork from its source checkout:

```bash
git clone https://github.com/Dillflix/teamarr.git
cd teamarr
docker compose up -d --build teamarr
```

Open `http://YOUR_SERVER_IP:9195`. The supplied Compose service builds
`dillflix-teamarr:local` from this repository. No override file is needed.
Docker may download the Python, Node and other build dependencies; it does not
pull the upstream Teamarr application image.

The existing `./data:/app/data` mount preserves your database, settings and logs.
Keep any additional environment settings or mounts you use for
`TEAMARR_BROADCAST_CONFIG`.

For subsequent updates, run from the same checkout:

```bash
git pull --ff-only
docker compose up -d --build teamarr
docker compose logs -f --tail=100 teamarr
```

A plain `docker compose up -d` also builds the service because its pull policy is
`build`; Docker reuses unchanged build layers. The upstream
`ghcr.io/pharaoh-labs/teamarr` images do not contain this fork's changes.

See the [fork installation guide](docs/guide/installation.md) and
[unified controller feed](docs/guide/controller-feed.md) for deployment and API details.

## Documentation

**Official Docs**: [pharaoh-labs.github.io/teamarr](https://pharaoh-labs.github.io/teamarr/) — User Guide, Technical Reference, Supported Leagues

## Contributing

Bug reports, league requests, and pull requests are welcome. See the [Contributing Guide](CONTRIBUTING.md). PRs target `dev`.

## License

Teamarr is free software licensed under the [GNU Affero General Public License v3.0 only](LICENSE) (AGPL-3.0-only).

Copyright (C) 2025-2026 Pharaoh Labs and Teamarr contributors.

If you run a modified Teamarr for other people over a network, the AGPL requires you to offer them the corresponding source.

Releases before v2.18.0 were offered under the MIT License as declared in this README, and those historical permissions remain unaffected.

## Attribution

Teamarr reads publicly available sports data and artwork from ESPN and other providers. All team names, logos, and trademarks are property of their respective owners.
