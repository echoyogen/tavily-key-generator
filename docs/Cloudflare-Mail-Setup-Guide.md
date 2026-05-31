# Cloudflare Mail Setup Guide

[中文版](./Cloudflare%E9%82%AE%E4%BB%B6%E8%AE%BE%E7%BD%AE%E8%AF%A6%E8%A7%A3.md)

Universal edition: how to build a reusable “unlimited alias domain mail” setup with Cloudflare Email Routing, Catch-all, and Email Workers.

> In this guide, “unlimited domain mail” really means “unlimited alias-style mailboxes on your own domain”.
> In other words, you do not have to pre-create every mailbox account one by one.
> You can still receive mail sent to arbitrary random addresses under your domain.

This guide was cross-checked against Cloudflare’s official documentation on `2026-03-16`.

---

## 1. Who this guide is for

This guide is not only for `tavily-key-generator`.

It is useful if you want to:

- turn your own domain into an “unlimited alias” receiving endpoint
- receive verification codes, login links, and confirmation emails without creating many mailbox accounts
- connect domain mail to scripts, automation, or test environments
- forward mail to Gmail, Outlook, or a business inbox
- build your own mail API so programs can query message content over HTTP

If you only want simple forwarding, this guide works.  
If you want a programmable mail pipeline, this guide also works.

---

## 2. What “unlimited domain mail” really means

People often misunderstand this phrase.

It does **not** mean:

1. Cloudflare gives you an unlimited number of full traditional mailbox accounts
2. Cloudflare gives you a built-in inbox UI like Gmail

What it really means is:

### you can receive mail sent to practically unlimited random addresses under your domain, without manually creating each mailbox first

For example:

```text
anything-1@example.com
signup-abc@example.com
tavily-x8y9z0@example.com
notify-order-123@example.com
```

You do not need to pre-create all of these addresses individually.

You only need:

1. Cloudflare Email Routing
2. Catch-all
3. a final destination or processing layer

That said, it is still not literally infinite in a platform-level sense.

According to Cloudflare’s official docs as of `2026-03-16`, you still need to keep in mind:

- a default limit of `200` routing rules
- a default limit of `200` addresses
- a current message size limit of `25 MiB`
- Worker resource limits if you process mail through Email Workers

If those defaults are not enough, Cloudflare also documents a limit-increase request path.

So the key advantage is not “no limits anywhere”.

The real advantage is:

### you no longer need to manually maintain hundreds or thousands of actual mailbox accounts

---

## 3. What this setup is good for

This setup works very well for:

- verification-code mailboxes
- automated signup flows
- QA and test environments
- notification aggregation
- service-specific alias addresses
- internal tooling
- disposable or semi-disposable mail pipelines

It is **not** a full replacement for a traditional business mailbox platform if you need:

- inbox and sent-mail UI
- drafts
- a full per-user mailbox product
- standard IMAP / POP3 mailbox behavior for humans

For that, you would still want a dedicated mail provider such as:

- Google Workspace
- Microsoft 365
- Zoho Mail
- Fastmail

Cloudflare Email Routing is best thought of as:

**a powerful inbound mail routing and processing layer**

not a complete mailbox product.

Cloudflare’s docs also explicitly state:

### Email Routing does not process outbound email and does not provide an SMTP server.

So if you need sending capability, you still need a separate outbound mail solution.

---

## 4. The two main architecture options

There are two practical ways to use this system.

### Mode A: Simple forwarding

Best for personal or lightweight use.

```text
Mail sent to your domain
        ↓
Cloudflare Email Routing
        ↓
Forwarded to Gmail / Outlook / business inbox
```

Pros:

- fastest to set up
- no code required
- great for normal subscriptions and registration mail

Cons:

- weak automation story
- not convenient for direct programmatic access
- less flexible for code extraction and custom routing logic

### Mode B: Worker automation mode

Best for developers and automation-heavy workflows.

```text
Mail sent to your domain
        ↓
Cloudflare Email Routing
        ↓
Catch-all matches
        ↓
Email Worker processes the message
        ↓
D1 / KV / R2 / Webhook / your API
        ↓
your project or automation reads the result
```

Pros:

- perfect for automation
- easy to turn into a mail API
- ideal for extracting OTP codes, links, and structured data
- easy to integrate with dashboards, scripts, and internal systems

Cons:

- requires a small amount of Worker code
- requires basic understanding of D1 or API design

If you only need normal mail forwarding, choose Mode A.  
If you want programs to consume mail, choose Mode B.

---

## 5. Main domain or subdomain?

This decision matters more than it looks.

### Best practice: use a dedicated subdomain

For example:

- `mail.example.com`
- `notify.example.com`
- `signup.example.com`
- `box.example.com`

Why this is better:

1. it avoids interfering with your main domain
2. the DNS setup stays cleaner
3. it is easier to troubleshoot
4. it fits automation-specific use cases much better

### Do not force this onto a domain already running another mail service

Cloudflare’s docs are clear: when Email Routing is active for the configured domain, other active MX-based mail services on that same configured domain will conflict with it.

So if your main domain already uses:

- Google Workspace
- Microsoft 365
- another enterprise mail provider

the safest option is:

**create a dedicated subdomain for this purpose**

---

## 6. What you need before starting

Prepare the following:

1. a domain already managed by Cloudflare
2. access to the Cloudflare Dashboard
3. a chosen domain or subdomain
4. if you want automation mode, local access to `node`, `npm`, and `wrangler`

If `wrangler` is not installed:

```bash
npm install -g wrangler
```

Then authenticate:

```bash
wrangler login
```

---

## 7. Step 1: Enable Email Routing

Open:

```text
Cloudflare Dashboard
-> your domain
-> Email
-> Email Routing
```

The first time you use it, Cloudflare will guide you through enabling Email Routing.

The core actions are:

1. enable Email Routing
2. let Cloudflare add the required DNS records

This usually involves:

- `MX`
- `TXT`

### Three common problems here

#### 1. Existing MX conflicts

If the domain already uses another mail provider, Cloudflare will usually warn you.

If you keep the conflicting MX records, Email Routing usually will not work properly.

#### 2. SPF conflicts

If Cloudflare reports SPF issues, fix them early.

Multiple SPF records are a common source of mail-routing trouble.

#### 3. Manual edits to Cloudflare-managed mail DNS

Once Cloudflare creates the mail-related DNS records for Email Routing, avoid manually editing them unless you really know why.

---

## 8. Step 2: If you want a subdomain, add it first

If you want to use something like:

```text
signup.example.com
```

instead of the zone apex domain, first add that subdomain to Email Routing.

Path:

```text
Email
-> Email Routing
-> Settings
-> Add subdomain
```

Once this is done, Routing Rules will let you choose between:

- the top-level zone domain
- any configured Email Routing subdomain

---

## 9. Step 3: Understand the three key concepts

Cloudflare Email Routing becomes much easier once these three concepts are clear.

### 1. Custom address

This is an explicitly created address rule, for example:

```text
info@example.com
news@example.com
verify@example.com
```

Use this when you know the exact fixed addresses you want.

### 2. Catch-all

This is the most important part for the “unlimited alias” setup.

Its job is:

**to catch addresses that do not have explicit rules**

This is what makes large numbers of random addresses practical.

Instead of creating:

```text
a1@example.com
a2@example.com
a3@example.com
random-1@example.com
random-2@example.com
```

one by one, Catch-all lets one route handle them all.

### 3. Subaddressing (plus addressing)

Cloudflare now supports addresses like:

```text
user+tag@example.com
```

This is useful when you want a single existing address plus a dynamic tag.

For example:

```text
newsletter+reddit@example.com
newsletter+github@example.com
```

This is helpful for source labeling, but it is not a replacement for Catch-all.

In short:

- use Catch-all for arbitrary random local-parts
- use Subaddressing to add tags to an existing base address

---

## 10. Step 4: Decide where the mail should go

At the end of the routing chain, you normally choose one of two destinations.

### Option A: Forward to a real mailbox

Such as:

- Gmail
- Outlook
- a business mailbox

This is the simplest route:

```text
Custom address / Catch-all
-> Forward to verified destination address
```

Good for:

- normal receiving
- personal alias mail
- website registrations
- newsletter routing

### Option B: Send to an Email Worker

This is better for automation and integration work:

```text
Custom address / Catch-all
-> Send to Email Worker
```

Good for:

- OTP extraction
- verification-link parsing
- building a mail API
- database storage
- webhook delivery
- project integrations

If your real goal is “let code read the mail”, choose the Worker route.

---

## 11. Step 5: Enable Catch-all

Go to:

```text
Email
-> Email Routing
-> Routes
```

Find `Catch-all address`.

Then:

1. turn it on so it becomes `Active`
2. choose the action
3. save

The action can be:

- forward to a destination address
- send to a Worker

### Recommended patterns

If you only want all random aliases to land in Gmail:

```text
Catch-all -> Forward to Gmail
```

If you want a programmable mail system:

```text
Catch-all -> Send to Worker
```

This is the key step behind the “unlimited alias domain mail” workflow.

---

## 12. Step 6: How to configure the simple forwarding mode

If you only want your domain mail forwarded to a normal mailbox, this is the shortest path.

### Setup flow

1. enable Email Routing
2. add a destination address
3. verify that destination
4. create a Custom address or enable Catch-all
5. choose `Forward`
6. select the verified destination mailbox

### Example

You might set up:

```text
newsletter@example.com -> yourname@gmail.com
billing@example.com -> yourname@gmail.com
Catch-all@example.com -> yourname@gmail.com
```

Then mail sent to:

```text
anything@example.com
signup-test@example.com
random-2026@example.com
```

can all end up in your Gmail.

### Who this mode is for

Good for:

- general mail receiving
- website signups
- subscription management
- personal alias routing

Not ideal for:

- automatic code extraction
- direct programmatic mail access
- mail APIs

---

## 13. Step 7: How to configure the automation mode

If you want code to read incoming messages directly, use this path.

Recommended structure:

```text
Cloudflare Email Routing
        ↓
Catch-all
        ↓
Email Worker
        ↓
D1 / KV / R2 / Webhook / API
        ↓
your project or automation
```

The most practical default design is:

- `Email Worker` receives the message
- `D1` stores the parsed content
- `fetch()` exposes an HTTP API

This is the most reusable general-purpose design.

---

## 14. Step 8: Create a generic mail Worker

Run locally:

```bash
npm create cloudflare@latest mail-gateway-api
cd mail-gateway-api
npm i postal-mime
```

Why `postal-mime`?

Cloudflare hands the Worker a raw email message.  
Most automation flows want a parsed structure like:

- `subject`
- `text`
- `html`
- `from`
- `to`

---

## 15. Step 9: Create a D1 database

Create the database:

```bash
npx wrangler d1 create mail_gateway
```

Save the returned `database_id`.

Then create `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  message_to TEXT NOT NULL,
  message_from TEXT,
  subject TEXT,
  text TEXT,
  html TEXT,
  received_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_to_time
ON messages(message_to, received_at DESC);
```

Apply it:

```bash
npx wrangler d1 execute mail_gateway --file=schema.sql
```

This schema is enough for most OTP, signup, and notification scenarios.

---

## 16. Step 10: Minimal Worker example

Put this in `src/index.ts`:

```ts
import PostalMime from "postal-mime";

export interface Env {
  DB: D1Database;
  API_TOKEN: string;
}

function unauthorized() {
  return new Response("Unauthorized", { status: 401 });
}

function checkAuth(req: Request, env: Env) {
  const auth = req.headers.get("Authorization") || "";
  return auth === `Bearer ${env.API_TOKEN}`;
}

export default {
  async email(message: ForwardableEmailMessage, env: Env) {
    const parsed = await new PostalMime().parse(message.raw);
    const id =
      parsed.messageId ||
      `${String(message.to).toLowerCase()}-${Date.now()}-${crypto.randomUUID()}`;

    await env.DB.prepare(
      `INSERT OR REPLACE INTO messages
       (id, message_to, message_from, subject, text, html, received_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)`
    )
      .bind(
        id,
        String(message.to).toLowerCase(),
        parsed.from?.address || "",
        parsed.subject || "",
        parsed.text || "",
        typeof parsed.html === "string" ? parsed.html : "",
        Date.now()
      )
      .run();
  },

  async fetch(req: Request, env: Env) {
    if (!checkAuth(req, env)) {
      return unauthorized();
    }

    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/messages") {
      const address = (url.searchParams.get("address") || "").trim().toLowerCase();
      if (!address) {
        return Response.json({ error: "missing address" }, { status: 400 });
      }

      const result = await env.DB.prepare(
        `SELECT id, message_to, message_from, subject, text, html, received_at
         FROM messages
         WHERE message_to = ?1
         ORDER BY received_at DESC
         LIMIT 20`
      )
        .bind(address)
        .all();

      return Response.json({
        messages: result.results || [],
      });
    }

    return new Response("Not found", { status: 404 });
  },
};
```

This code does two things:

### `email()`

Cloudflare calls this when a message arrives.  
We parse it and store it in D1.

### `fetch()`

Your scripts or applications can call:

```text
GET /messages?address=xxx@example.com
```

to read the latest mail for a specific alias address.

---

## 17. Step 11: Configure `wrangler.toml`

Use a minimal config like this:

```toml
name = "mail-gateway-api"
main = "src/index.ts"
compatibility_date = "2026-03-16"

[[d1_databases]]
binding = "DB"
database_name = "mail_gateway"
database_id = "replace-with-your-database-id"
```

Then create a Bearer token for the API:

```bash
npx wrangler secret put API_TOKEN
```

Use a long random string.

Its purpose is simple:

**protect your mail-reading API from unauthorized access**

---

## 18. Step 12: Deploy the Worker

Run:

```bash
npx wrangler deploy
```

You will usually get a URL like:

```text
https://mail-gateway-api.xxx.workers.dev
```

This URL can now be used by:

- scripts
- projects
- dashboards
- internal tools

to query mail content.

---

## 19. Step 13: Point Cloudflare Routing to the Worker

Now go back to Cloudflare:

```text
Email
-> Email Routing
-> Routes
```

Choose either:

- a Custom address
- or Catch-all

Set the `Action` to:

```text
Send to a Worker
```

Then select the Worker you deployed.

At this point the pipeline is complete:

```text
mail sent to arbitrary alias address
-> Cloudflare Catch-all matches
-> Email Worker receives it
-> D1 stores it
-> API returns it
```

---

## 20. Four practical use cases

### Use case 1: registration-only domain mail

For example, use:

```text
signup.example.com
```

Then register services with random aliases such as:

```text
reddit-001@signup.example.com
github-002@signup.example.com
shop-003@signup.example.com
```

Why this is useful:

- your real mailbox stays hidden
- the alias itself tells you where it was used
- leaks become easier to trace

### Use case 2: automated OTP mailboxes

Perfect for:

- signup bots
- test environments
- QA verification flows

Best pattern:

```text
Catch-all -> Worker -> API
```

Your code reads the API directly, without opening a mailbox UI.

### Use case 3: internal notification intake

You can assign different aliases to different notification sources:

```text
billing@notify.example.com
alarm@notify.example.com
backup@notify.example.com
```

Then let the Worker route them by sender, subject, or downstream system.

### Use case 4: disposable mailbox infrastructure

You can extend the Worker with:

- automatic expiration
- scheduled cleanup
- retention windows
- allowed-sender checks

This lets you build your own disposable-mail platform on top of the same foundation.

---

## 21. How to test the setup

Use this order.

### Test 1: send one manual test email

Pick an address that should match Catch-all, for example:

```text
test-123@signup.example.com
```

Send a message to it from another mailbox.

Cloudflare officially recommends not sending the test from the same destination mailbox to itself, because some providers may treat it as a duplicate and hide it.

### Test 2: for simple forwarding mode

Check whether the destination inbox actually received the message.

### Test 3: for Worker automation mode

Query the API:

```bash
curl -H "Authorization: Bearer your-token" \
  "https://mail-gateway-api.xxx.workers.dev/messages?address=test-123@signup.example.com"
```

If you get a `messages` array back, the flow is working.

---

## 22. Most common mistakes

### 1. Forgetting Catch-all and expecting random aliases to work

They usually will not.

If you do not create every address explicitly and you also do not enable Catch-all, most random aliases will not behave the way you expect.

### 2. Reusing a production mail domain already backed by another MX-based provider

This is one of the most common sources of conflict.

The safest fix is still:

**use a dedicated subdomain**

### 3. Assuming Cloudflare provides a built-in inbox API

It does not.

Email Routing handles inbound routing and processing.  
If you want “query messages by alias address”, you usually need your own Worker + D1 + API layer.

### 4. Exposing your mail API without auth

If you publish `/messages?address=...`, protect it.

The simplest option is:

- `Authorization: Bearer ...`

You can also add:

- Cloudflare Access
- IP allowlists
- private-network-only access

### 5. Treating Subaddressing as a replacement for Catch-all

They are not the same.

- `user+tag@example.com` is great for tagging an existing base address
- Catch-all is what you want for truly arbitrary alias local-parts

---

## 23. Real limits and boundaries

To avoid overselling the word “unlimited”, here is the practical truth.

### 1. Cloudflare still has official service limits

For example:

- `200` routing rules by default
- `200` addresses by default
- a `25 MiB` message size cap
- Worker limits

So “unlimited” does not mean the platform has zero resource boundaries.

### 2. The real “infinite” part is the alias-management model

The real power of this approach is not:

“Cloudflare has no limits”

The real power is:

### you no longer need to manually maintain huge numbers of real mailbox accounts

With just:

- one domain or subdomain
- one Catch-all route
- one Worker logic path

you can handle very large numbers of random alias addresses cleanly.

---

## 24. If you want the shortest path, do this

Use this minimum working stack:

1. one dedicated subdomain such as `signup.example.com`
2. Email Routing enabled
3. Catch-all enabled
4. Catch-all set to `Send to Worker`
5. Worker stores mail in D1
6. Worker exposes `GET /messages?address=...`

That stack is already enough for:

- signup bots
- OTP automation
- testing environments
- disposable mail pipelines
- internal notification intake

---

## 25. As one example: how this repo can use the same pattern

Even though this guide is generic, here is a concrete repository example.

If you want to connect this generic setup to the current repo, the project mainly reads:

```env
EMAIL_PROVIDER=cloudflare
EMAIL_API_URL=https://mail-gateway-api.xxx.workers.dev
EMAIL_API_TOKEN=your-worker-token
EMAIL_DOMAIN=signup.example.com
```

If you want multiple domains:

```env
EMAIL_PROVIDER=cloudflare
EMAIL_API_URL=https://mail-gateway-api.xxx.workers.dev
EMAIL_API_TOKEN=your-worker-token
EMAIL_DOMAINS=signup.example.com,verify.example.com
```

Inside this repo, those values drive:

- random mailbox generation
- calls to your `/messages` API
- extraction of verification codes and links

But that is only one application of this pattern, not the point of the guide itself.

---

## 26. Official references

These were the main Cloudflare official docs cross-checked during this rewrite:

- [Overview](https://developers.cloudflare.com/email-routing/)
- [Enable Email Routing](https://developers.cloudflare.com/email-routing/get-started/enable-email-routing/)
- [Configure Rules and Addresses](https://developers.cloudflare.com/email-routing/setup/email-routing-addresses/)
- [Subdomains](https://developers.cloudflare.com/email-routing/setup/subdomains/)
- [Enable Email Workers](https://developers.cloudflare.com/email-routing/email-workers/enable-email-workers/)
- [Email Workers](https://developers.cloudflare.com/email-routing/email-workers/)
- [Runtime API](https://developers.cloudflare.com/email-routing/email-workers/runtime-api/)
- [Limits](https://developers.cloudflare.com/email-routing/limits/)
- [Test Email Routing](https://developers.cloudflare.com/email-routing/get-started/test-email-routing/)

---

## 27. One final practical sentence

If you want a reusable, automation-friendly “unlimited alias domain mail” system, the most practical answer is not:

“create lots of mailbox accounts by hand”

It is:

### Cloudflare Email Routing + Catch-all + Email Worker + your own mail-reading interface

Once that foundation is in place, you can reuse it for signups, automation, testing, internal tools, and project integrations like this repository.
