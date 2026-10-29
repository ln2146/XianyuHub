# XianyuHub 封面生成说明

制作日期：2026-10-29。使用内置 image_gen 工具生成，未使用 API/CLI 回退。

成品：`xianyuhub-cover.png`，适用于 GitHub README 和社交分享的横版封面。

依据项目 README、`frontend/public/icon.svg` 与 `frontend/src/styles.css` 确定产品定位、鱼形标志和翡翠绿品牌色。主文案为“淘好货，管好店”，突出选品雷达、AI 客服与虚拟商品自动发货。画面为品牌概念插画，不是应用界面截图。

英文封面：`xianyuhub-cover-en.png`，使用内置 image_gen 编辑中文封面，仅本地化文字，并调整英文标题的字宽和字号。分别用于 `README.md` 与 `README_EN.md`。

## 英文封面提示词

```text
Use case: text-localization.
Edit target: the supplied XianyuHub Chinese cover. Produce its English localized companion, preserving the exact landscape composition, mint and emerald palette, white left-facing fish logo, radar with laptop/headphones/camera, connected chat bubbles and digital-delivery envelope, water reflections, light, materials, proportions, footer icons and margins. Change text only, adjusting font sizes and line breaks within the existing text zones so no letters overlap the radar or illustrations.

Exact English lettering:
In the upper-left brand area, replace the Chinese brand name and the smaller English line with one clear large wordmark "XianyuHub", aligned beside the existing fish app icon. No Chinese characters remain.
The large two-line headline becomes:
"Find great deals."
"Run your shop."
Keep it bold, dark forest green and balanced, large but within the left text column.
Supporting line:
"Your self-hosted Xianyu assistant"
Footer feature strip:
"Product radar · AI replies · Digital delivery"
Second footer line:
"Self-hosted · Multi-account · Buying & selling"
Repository URL stays exactly:
"github.com/ln2146/XianyuHub"

Keep the footer's three simple feature icons and GitHub symbol, with readable orderly text and no overlaps. "Digital delivery" refers to virtual goods, not parcel shipping. Preserve all original imagery and the warm amber accents. Final artwork only, no additional claims, no official marketplace branding, no watermark, no QR code, no new decorative elements.
```

### 英文标题排版修订

```text
Use case: text-localization / precise-object-edit.
Edit target: this English XianyuHub cover. Make ONE targeted correction: improve typography of the large two-line headline on the left.
Current headline uses an excessively narrow condensed font. Replace it with a clean, naturally proportioned bold sans-serif (normal width, no compression, no stretching), and REDUCE its size so there is real whitespace between text and the radar. Keep the exact words and line breaks:
"Find great deals."
"Run your shop."
Set headline approximately 40% shorter in height than its current rendering and give the two lines a comfortable gap. Align the left edge with the support line below. Its rightmost letter should finish before the radar edge; do not distort letterforms to force fitting. The natural smaller bold type should look calm, professional and intentional.

Preserve EVERYTHING ELSE: XianyuHub wordmark, fish icon, exact support "Your self-hosted Xianyu assistant", all footer labels, repository URL, emerald radar and product objects, speech bubbles, digital envelope, water, lighting, mint background, landscape proportions. Do not change any other wording, object or color. No new additions or watermark.
```

## 中文封面完整提示词

```text
Use case: ads-marketing.
Asset type: a premium horizontal GitHub README / social sharing cover for the real open-source project 鱼塘管家 XianyuHub. Approximately 1.91:1 aspect ratio, high resolution.

Verified product brief: XianyuHub is a self-hosted assistant for the Chinese secondhand marketplace Xianyu. Buyers use product radar, search, price tracking and seller analysis. Sellers use AI customer replies, unified multi-account conversations and automated delivery of virtual goods. It runs on the user's own computer or NAS. This is an independent community project, not an official marketplace product.

Art direction: an elegant, purposeful software brand poster. Follow the existing app's emerald identity: rich emerald #047857 / #1e9e6a, dark ink #0f172a, porcelain white and very pale mint #ecfdf5, with tiny warm amber accents. Tactile sculptural illustration, clean editorial typography, studio lighting and thoughtful whitespace. Make it feel like a trustworthy modern tool for managing a small shop. Distinctive and restrained, not a generic SaaS dashboard template.

Composition:
Left about 48%: strong readable branding and headline, with generous margins. Integrate a simple small green rounded-square brand mark with a white LEFT-FACING fish silhouette and a green eye (this is the project's existing visual motif). Main Chinese brand name "鱼塘管家", paired with the exact English name "XianyuHub". Headline is the main visual anchor, in two bold lines:
"淘好货，"
"管好店。"
Supporting sentence below:
"自部署的闲鱼买卖助手"
Keep all copy on the left optically balanced, with no visual object behind the letters.

Right about 52%: one cohesive sculptural 'fishpond hub' illustration, clearly separated from text. A large refined emerald circular radar platter, with subtle concentric rings and a quiet sweeping translucent beam, discovers a few small secondhand goods silhouettes (a laptop, headphones and camera), all unbranded. At the heart of the scene is a beautiful solid emerald medallion bearing the project's simple white left-facing fish. An elegant continuous path flows from the radar to a minimal paired chat-bubble form and to an understated virtual-goods delivery envelope with a small generic key-card token. Let these objects read as a single connected composition: find goods, converse, deliver. The virtual delivery token is an abstract blank voucher, not a real credential, not a payment card. Materials are matte ceramic and translucent mint glass, with subtle metallic detail; grounding shadows and restrained depth. Avoid floating dashboard windows, tables, mini UI screenshots, cluttered app cards, chart metrics or invented conversation text. All hero elements remain fully inside the frame.

Bottom: a clean aligned information strip, integrated into the background with a thin quiet rule, containing three small simple visual symbols and the exact feature text:
"选品雷达 · AI 客服 · 虚拟商品自动发货"
Then a smaller clear line:
"自部署 · 多账号 · 买卖一体"
And a quiet but legible repository URL:
"github.com/ln2146/XianyuHub"

Text constraints: Render all specified Chinese and English precisely. No extra slogans or technical stack badges. No invented statistics, prices, revenue, sales counts or guaranteed returns. Do not imply official affiliation with Xianyu/Alibaba. No promise that physical products can be shipped automatically, no claim that all data stays local, no claim of zero account risk. No actual vendor logos, no QR code, no watermark. Final artwork only, edge to edge; not a webpage screenshot. Strong hierarchy, calm spacious layout, sharp readable typography and a beautiful emerald fish/radar composition.
```
