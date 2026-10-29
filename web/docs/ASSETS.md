# Image and brand assets

## Logo

| File | What it is |
| --- | --- |
| `public/brand/rescrub-logo-original.png` | The supplied lowercase-r logo (1254×1254, transparent). Source of truth. |
| `public/brand/rescrub-mark.png` | Cropped to the artwork, 127×128, shown at 26px in the header. |
| `app/icon.png` | 512×512 square with ~6% padding: the browser-tab icon. |

Colors in the logo: forest green `#033F2E`, lavender `#A598FA`. These are also
`--color-primary` and `--color-accent-mark` in `app/globals.css`.

To regenerate the cropped versions after a logo change, crop to the artwork's
transparent bounds without stretching. Keep the original's proportions.

## Homepage photo

- **What:** a blue-gloved hand reaching for steel instruments on a pale surface.
- **Photographer:** syahmi syahir (https://unsplash.com/@subspace_stills)
- **Source:** https://unsplash.com/photos/a-hand-in-a-blue-glove-is-pointing-at-a-set-of-surgical-instruments-bmNzLUhu9Xo
- **License:** Unsplash License (free to use, commercial or not, no permission
  needed; credit appreciated). https://unsplash.com/license
- **How it's served:** loaded from Unsplash's CDN
  (`https://images.unsplash.com/photo-1728102199887-a285f8957c5d`) through
  `next/image`. The address is allowed in `next.config.ts`. To self-host it
  instead, download it from the source page, put it in `public/`, and change
  `HERO_PHOTO` in `app/page.tsx`.
