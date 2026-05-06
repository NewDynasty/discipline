// Shared navigation + auth for all Command Center pages
(function(){
  // ── Theme (unify legacy keys: cc-theme, docs-theme → cc_theme) ──
  let t=localStorage.getItem('cc_theme');
  if(!t){const alt=localStorage.getItem('cc-theme')||localStorage.getItem('docs-theme');if(alt){localStorage.setItem('cc_theme',alt);localStorage.removeItem('cc-theme');localStorage.removeItem('docs-theme');t=alt}}
  if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme:dark)').matches)){
    document.documentElement.setAttribute('data-theme','dark');
  }

  // ── Inject CSS ──
  if(!document.getElementById('shared-nav-css')){
    const s=document.createElement('style');
    s.id='shared-nav-css';
    s.textContent=`
.nav{background:rgba(255,255,255,.72);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid rgba(0,0,0,.06);padding:12px 24px;display:flex;align-items:center;gap:24px;position:sticky;top:0;z-index:10}
.nav a{text-decoration:none;color:#86868b;font-size:14px;transition:color .2s}.nav a:hover{color:#0071e3}
.nav-brand{font-weight:700;color:#1d1d1f!important;font-size:15px!important}
.nav-active{color:#0071e3!important;font-weight:600}[data-theme="dark"] .nav-active{color:#f59e0b!important}
[data-theme="dark"] .nav{background:rgba(10,10,15,.85);border-bottom-color:#1e293b}
[data-theme="dark"] .nav a{color:#94a3b8}[data-theme="dark"] .nav a:hover{color:#f59e0b}
[data-theme="dark"] .nav-brand{color:#e2e8f0!important}
.nav-inner{display:flex;align-items:center;gap:24px;max-width:1100px;margin:0 auto;width:100%}
.nav-right{margin-left:auto;display:flex;align-items:center;gap:12px}
.theme-toggle{background:none;border:1px solid rgba(0,0,0,.12);border-radius:8px;padding:5px 12px;cursor:pointer;font-size:13px;color:#86868b;line-height:1.3}
[data-theme="dark"] .theme-toggle{border-color:#334155;color:#94a3b8}
.nav-hamburger{display:none;background:none;border:none;font-size:20px;cursor:pointer;color:#86868b;padding:4px 8px}
.nav-auth-btn{background:none;border:1px solid rgba(0,0,0,.12);border-radius:8px;padding:5px 12px;cursor:pointer;font-size:13px;color:#86868b;transition:all .15s;line-height:1.3;white-space:nowrap}
.nav-auth-btn:hover{border-color:#0071e3;color:#0071e3}
.nav-auth-btn.logged-in{border-color:#30d158;color:#30d158;font-weight:500}
[data-theme="dark"] .nav-auth-btn{border-color:#334155;color:#94a3b8}
[data-theme="dark"] .nav-auth-btn:hover{border-color:#f59e0b;color:#f59e0b}
[data-theme="dark"] .nav-auth-btn.logged-in{border-color:#4ade80;color:#4ade80}
@media(max-width:640px){.nav{padding:10px 16px}.nav-inner{gap:0;flex-wrap:wrap}.nav-inner .nav-link{display:none}.nav-inner.open .nav-link{display:block;width:100%;padding:8px 0;border-bottom:1px solid rgba(0,0,0,.06)}.nav-hamburger{display:block}[data-theme="dark"] .nav-inner .nav-link{border-bottom-color:#1e293b}}

/* Login overlay */
.login-overlay{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.35);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);opacity:0;pointer-events:none;transition:opacity .25s}
.login-overlay.show{opacity:1;pointer-events:auto}
.login-box{background:#fff;border-radius:18px;padding:40px 36px;width:340px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,.15)}
[data-theme="dark"] .login-box{background:#1e293b;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.login-title{font-size:22px;font-weight:700;letter-spacing:-.5px;margin-bottom:4px;color:#1d1d1f}
[data-theme="dark"] .login-title{color:#e2e8f0}
.login-sub{font-size:13px;color:#86868b;margin-bottom:24px}
.login-input{width:100%;padding:12px 14px;border:1px solid #d2d2d7;border-radius:10px;font-size:15px;outline:none;transition:border .2s;background:#fff;color:#1d1d1f;box-sizing:border-box}
.login-input:focus{border-color:#0071e3}
[data-theme="dark"] .login-input{background:#0a0a0f;border-color:#334155;color:#e2e8f0}
[data-theme="dark"] .login-input:focus{border-color:#f59e0b}
.login-btn{width:100%;padding:12px;border:none;border-radius:10px;background:#0071e3;color:#fff;font-size:15px;font-weight:600;cursor:pointer;margin-top:14px;transition:background .15s}
.login-btn:hover{background:#0077ed}
.login-btn:disabled{opacity:.5;cursor:not-allowed}
[data-theme="dark"] .login-btn{background:#f59e0b;color:#0a0a0f}
.login-error{font-size:12.5px;color:#ff3b30;margin-top:10px;min-height:18px}

/* Page content gate */
.page-gate{display:none}
.page-gate.visible{display:block}
    `;
    document.head.appendChild(s);
  }

  // ── Auth state ──
  const AUTH_KEY='cc_token';
  function getToken(){return localStorage.getItem(AUTH_KEY)}
  function setToken(t){localStorage.setItem(AUTH_KEY,t)}
  function clearToken(){localStorage.removeItem(AUTH_KEY)}

  // ── Build nav ──
  const pages=[
    {href:'/portal',label:'\u26a1 Command Center',brand:true},
    {href:'/portal#quick',label:'\u5feb\u901f\u8bbf\u95ee'},
    {href:'/docs',label:'\ud83d\udcda \u6587\u6863'},
    {href:'/knowledge',label:'\ud83e\udde0 \u77e5\u8bc6\u5e93'},
    {href:'/models',label:'\ud83e\udd16 \u6a21\u578b'},
    {href:'/graph',label:'\ud83d\udd79\ufe0f \u56fe\u8c31'},
    {href:'/deploy',label:'\ud83d\ude80 \u90e8\u7f72'},
    {href:'/static/hotspot.html',label:'\uD83D\uDD25 \u70ED\u70B9'},
  ];
  const cur=location.pathname.replace(/\/$/,'');
  const old=document.querySelector('.nav');
  if(old)old.remove();
  const nav=document.createElement('nav');
  nav.className='nav';
  const inner=document.createElement('div');
  inner.className='nav-inner';
  pages.forEach(p=>{
    const a=document.createElement('a');
    a.href=p.href;
    a.textContent=p.label;
    a.className=p.brand?'nav-brand':'nav-link';
    const match=p.href.replace(/\/$/,'');
    if(cur===match&&!p.brand)a.classList.add('nav-active');
    inner.appendChild(a);
  });

  // Right side container (theme + auth + hamburger)
  const right=document.createElement('div');
  right.className='nav-right';

  // Hamburger
  const burger=document.createElement('button');
  burger.className='nav-hamburger';
  burger.textContent='\u2630';
  burger.onclick=function(){inner.classList.toggle('open')};
  right.appendChild(burger);

  // Theme toggle
  const themeBtn=document.createElement('button');
  themeBtn.className='theme-toggle';
  themeBtn.textContent='\ud83c\udf13';
  themeBtn.onclick=function(){
    const d=document.documentElement;
    const isDark=d.getAttribute('data-theme')==='dark';
    d.setAttribute('data-theme',isDark?'light':'dark');
    localStorage.setItem('cc_theme',isDark?'light':'dark');
  };
  right.appendChild(themeBtn);

  // Auth button
  const authBtn=document.createElement('button');
  authBtn.className='nav-auth-btn';
  right.appendChild(authBtn);

  inner.appendChild(right);

  nav.appendChild(inner);
  document.body.insertBefore(nav,document.body.firstChild);

  // ── Login overlay ──
  const overlay=document.createElement('div');
  overlay.className='login-overlay';
  overlay.innerHTML=`
    <div class="login-box">
      <div class="login-title">\u26a1 Command Center</div>
      <div class="login-sub">\u767b\u5f55\u540e\u8bbf\u95ee\u95e8\u6237</div>
      <input type="password" class="login-input" id="cc-pw" placeholder="\u8f93\u5165\u5bc6\u7801" autocomplete="current-password">
      <button class="login-btn" id="cc-login-btn">\u767b\u5f55</button>
      <div class="login-error" id="cc-err"></div>
    </div>`;
  document.body.appendChild(overlay);

  const pwInput=document.getElementById('cc-pw');
  const loginBtn=document.getElementById('cc-login-btn');
  const errEl=document.getElementById('cc-err');

  // ── Gate content: wrap body children in .page-gate ──
  function gateContent(){
    // Don't double-wrap
    if(document.querySelector('.page-gate'))return;
    const gate=document.createElement('div');
    gate.className='page-gate';
    // Move everything except nav and overlay into gate
    while(document.body.children.length>2){
      // Skip the nav (first) and overlay (last)
      const last=document.body.children[document.body.children.length-2];
      if(last===nav||last===overlay)break;
      gate.prepend(document.body.removeChild(last));
    }
    // Also move anything between nav and overlay
    const toMove=[];
    let foundNav=false;
    for(const c of document.body.children){
      if(c===nav){foundNav=true;continue}
      if(c===overlay)break;
      if(foundNav)toMove.push(c);
    }
    toMove.forEach(c=>gate.appendChild(c));
    document.body.insertBefore(gate,overlay);
    return gate;
  }

  // ── Auth check ──
  async function checkAuth(){
    const token=getToken();
    if(!token){showLocked();return}
    try{
      const r=await fetch('/api/checkin/today',{headers:{'Authorization':'Bearer '+token}});
      if(r.ok){showUnlocked();return}
      if(r.status===401){clearToken();showLocked();return}
      // Other errors - assume ok (API might be down)
      showUnlocked();
    }catch(e){
      // Network error - show content anyway
      showUnlocked();
    }
  }

  function showLocked(){
    overlay.classList.add('show');
    authBtn.textContent='\u767b\u5f55';
    authBtn.classList.remove('logged-in');
    authBtn.onclick=()=>pwInput.focus();
    const gate=document.querySelector('.page-gate');
    if(gate)gate.classList.remove('visible');
  }

  function showUnlocked(){
    overlay.classList.remove('show');
    authBtn.textContent='\u2713 \u5df2\u767b\u5f55';
    authBtn.classList.add('logged-in');
    authBtn.onclick=doLogout;
    const gate=document.querySelector('.page-gate');
    if(gate)gate.classList.add('visible');
  }

  async function doLogin(){
    const pw=pwInput.value;
    if(!pw)return;
    loginBtn.disabled=true;
    errEl.textContent='';
    try{
      const r=await fetch('/api/auth/login',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({password:pw})
      });
      const d=await r.json();
      if(r.ok&&d.token){
        setToken(d.token);
        showUnlocked();
        pwInput.value='';
      }else{
        errEl.textContent=d.detail||'\u5bc6\u7801\u9519\u8bef';
      }
    }catch(e){
      errEl.textContent='\u7f51\u7edc\u9519\u8bef';
    }
    loginBtn.disabled=false;
  }

  async function doLogout(){
    const token=getToken();
    if(token){
      try{await fetch('/api/auth/logout',{method:'POST',headers:{'Authorization':'Bearer '+token}})}catch(e){}
    }
    clearToken();
    showLocked();
  }

  loginBtn.onclick=doLogin;
  pwInput.addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});

  // ── Init ──
  gateContent();
  checkAuth();
})();
