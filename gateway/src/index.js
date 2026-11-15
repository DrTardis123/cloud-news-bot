// cloud-news-bot 메일 중계 서버 (Cloudflare Worker) — 메일로 초안을 받고 싶을 때만 필요
//
// Claude 클라우드 세션은 HTTP(S)만 나갈 수 있어서 메일(SMTP)을 직접 못 보낸다.
// 그래서 세션은 이 Worker에 "이 메일 보내 줘"라고 HTTP로 부탁하고, 메일 비밀번호는 여기에만 둔다.
//
// 여러 봇이 같이 쓰도록 경로 첫 칸을 봇 이름으로 쓴다: /<bot>/...
// 봇마다 비밀값은 대문자 접두사로 구분한다 (예: news → NEWS_GATEWAY_KEY).
//
//   POST /<bot>/mail      클라우드 세션 → SMTP 메일 발송 대행  (Authorization: Bearer <GATEWAY_KEY>)
//   GET  /<bot>/health    설치 확인용 (비밀값 없이 ok만 돌려줌)
//
// 봇별 비밀값 (wrangler secret put <이름>):
//   <P>_GATEWAY_KEY, <P>_MAIL_HOST, <P>_MAIL_PORT, <P>_MAIL_USER, <P>_MAIL_PASS
//   <P>_BOT_NAME (선택, 메일 보내는 사람 이름)
import { WorkerMailer } from "worker-mailer";

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8" } });

function cfg(env, bot) {
  const P = bot.toUpperCase().replace(/[^A-Z0-9]/g, "_");
  const get = (k) => env[`${P}_${k}`];
  return get("GATEWAY_KEY") ? get : null;
}

function authorized(req, get) {
  return req.headers.get("authorization") === `Bearer ${get("GATEWAY_KEY")}`;
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
  async fetch(req, env) {
    const [, bot, action] = new URL(req.url).pathname.split("/");
    const get = bot && cfg(env, bot);
    if (get && req.method === "GET" && action === "health") return json({ ok: true, bot });
    if (!get || req.method !== "POST") return json({ ok: false, error: "not found" }, 404);
    if (!authorized(req, get)) return json({ ok: false, error: "unauthorized" }, 401);
    try {
      if (action === "mail") return await handleMail(req, get);
      return json({ ok: false, error: "unknown action" }, 404);
    } catch (e) {
      return json({ ok: false, error: String(e.message || e) }, 500);
    }
  },
};
