// cloud-news-bot 중계 서버 (Cloudflare Worker)
//
// 여러 봇이 같이 쓰도록 경로 첫 칸을 봇 이름으로 쓴다: /<bot>/...
// 봇마다 비밀값은 대문자 접두사로 구분한다 (예: blog → BLOG_TG_TOKEN).
//
//   POST /<bot>/telegram  텔레그램 webhook. 내 chat_id 메시지만 받아 Claude 예약 작업(/fire)으로 넘긴다
//   POST /<bot>/tg        클라우드 세션 → 텔레그램 발송 대행   (Authorization: Bearer <GATEWAY_KEY>)
//   POST /<bot>/mail      클라우드 세션 → SMTP 메일 발송 대행  (Authorization: Bearer <GATEWAY_KEY>)
//
// 봇별 비밀값 (wrangler secret put <이름>):
//   <P>_TG_TOKEN, <P>_CHAT_ID, <P>_WEBHOOK_SECRET, <P>_GATEWAY_KEY,
//   <P>_ROUTINE_URL, <P>_ROUTINE_TOKEN,
//   <P>_MAIL_HOST, <P>_MAIL_PORT, <P>_MAIL_USER, <P>_MAIL_PASS  (메일을 쓰는 봇만)
//   <P>_BOT_NAME (선택, 메일 보내는 사람 이름)
//
//   GET  /<bot>/health    설치 확인용 (비밀값 없이 ok만 돌려줌)
import { WorkerMailer } from "worker-mailer";

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8" } });

function cfg(env, bot) {
  const P = bot.toUpperCase().replace(/[^A-Z0-9]/g, "_");
  const get = (k) => env[`${P}_${k}`];
  return get("TG_TOKEN") ? get : null;
}

async function tgSend(get, text, parseMode) {
  const body = { chat_id: get("CHAT_ID"), text };
  if (parseMode) body.parse_mode = parseMode;
  const r = await fetch(`https://api.telegram.org/bot${get("TG_TOKEN")}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify(body),
  });
  return r.ok;
}

async function fireRoutine(get, text) {
  const r = await fetch(get("ROUTINE_URL"), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${get("ROUTINE_TOKEN")}`,
      "anthropic-beta": "experimental-cc-routine-2026-04-01",
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(`routine fire ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

function authorized(req, get) {
  return req.headers.get("authorization") === `Bearer ${get("GATEWAY_KEY")}`;
}

async function handleWebhook(req, get, ctx) {
  if (req.headers.get("x-telegram-bot-api-secret-token") !== get("WEBHOOK_SECRET")) return json({ ok: false }, 403);
  const update = await req.json().catch(() => ({}));
  const msg = update.message;
  // 내 채팅이 아니거나 글자가 없는 업데이트는 조용히 무시 (텔레그램엔 항상 200을 돌려줘야 재전송을 안 한다)
  if (!msg || !msg.text || String(msg.chat?.id) !== String(get("CHAT_ID"))) return json({ ok: true });
  ctx.waitUntil(
    (async () => {
      try {
        await fireRoutine(get, msg.text);
        await tgSend(get, "받았어. 클라우드에서 처리 시작할게 (준비에 1~3분 걸려).");
      } catch (e) {
        await tgSend(get, `클라우드 작업을 시작하지 못했어: ${e.message}`);
      }
    })(),
  );
  return json({ ok: true });
}

async function handleMail(req, get) {
  const { subject, html } = await req.json();
  const user = get("MAIL_USER");
  const port = Number(get("MAIL_PORT") || 587);
  const mailer = await WorkerMailer.connect({
    host: get("MAIL_HOST"),
    port,
    secure: port === 465, // 465는 처음부터 TLS, 587은 STARTTLS
    startTls: port !== 465,
    credentials: { username: user, password: get("MAIL_PASS") },
    authType: ["plain", "login"],
  });
  await mailer.send({ from: { name: get("BOT_NAME") || "뉴스봇", email: user }, to: { email: user }, subject, html });
  return json({ ok: true });
}

export default {
  async fetch(req, env, ctx) {
    const [, bot, action] = new URL(req.url).pathname.split("/");
    const get = bot && cfg(env, bot);
    if (get && req.method === "GET" && action === "health") return json({ ok: true, bot });
    if (!get || req.method !== "POST") return json({ ok: false, error: "not found" }, 404);
    try {
      if (action === "telegram") return await handleWebhook(req, get, ctx);
      if (!authorized(req, get)) return json({ ok: false, error: "unauthorized" }, 401);
      if (action === "tg") {
        const { text, parse_mode } = await req.json();
        return json({ ok: await tgSend(get, text, parse_mode) });
      }
      if (action === "mail") return await handleMail(req, get);
      return json({ ok: false, error: "unknown action" }, 404);
    } catch (e) {
      return json({ ok: false, error: String(e.message || e) }, 500);
    }
  },
};
