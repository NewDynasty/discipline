/* cc-components.js — Command Center 共享 JS 组件库
 * 使用方法: <script src="/static/cc-components.js"></script>
 * 依赖: cc-styles.css (可选，组件会自动注入必要样式)
 *
 * 组件:
 *   CC.toast(msg, type)           — 底部通知 (ok/error/warn/info)
 *   CC.fetch(url, opts)           — fetch 封装（自动带 token + 错误 toast）
 *   CC.loading.show(el)           — 显示骨架屏/加载状态
 *   CC.loading.hide(el)           — 恢复
 *   CC.badge(text, type)          — 返回 badge HTML 字符串
 *   CC.dot(online)                — 返回状态点 HTML
 */

window.CC = (function(){
  // ── Token helper ──
  function getToken(){
    return localStorage.getItem('cc_token');
  }

  // ── Toast ──
  let toastEl, toastTimer;
  function toast(msg, type){
    if(!toastEl){
      toastEl=document.createElement('div');
      toastEl.id='cc-toast';
      // Inject toast CSS if not already present
      if(!document.getElementById('cc-toast-css')){
        const s=document.createElement('style');
        s.id='cc-toast-css';
        s.textContent=`
#cc-toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%) translateY(80px);padding:12px 28px;border-radius:12px;font-size:14px;opacity:0;transition:all .3s;z-index:9999;pointer-events:none;background:#333;color:#fff;font-family:inherit}
#cc-toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
#cc-toast.error{background:#e8453c}
#cc-toast.ok{background:#34c759}
#cc-toast.warn{background:#f59e0b;color:#0a0a0f}
#cc-toast.info{background:#0071e3}`;
        document.head.appendChild(s);
      }
      document.body.appendChild(toastEl);
    }
    clearTimeout(toastTimer);
    toastEl.textContent=msg;
    toastEl.className='show '+(type||'');
    toastTimer=setTimeout(()=>toastEl.className='',3000);
  }

  // ── Fetch wrapper ──
  async function guardedFetch(url, opts={}){
    const token=getToken();
    const headers={...(opts.headers||{})};
    if(token)headers['Authorization']='Bearer '+token;
    if(opts.body&&typeof opts.body==='object'){
      headers['Content-Type']='application/json';
      opts.body=JSON.stringify(opts.body);
    }
    try{
      const r=await fetch(url,{...opts,headers});
      if(r.status===401){
        localStorage.removeItem('cc_token');
        toast('登录已过期，请重新登录','error');
        if(typeof reloadAuth==='function')reloadAuth();
        return r;
      }
      return r;
    }catch(e){
      toast('网络错误','error');
      throw e;
    }
  }

  // ── Loading ──
  const loading={
    show(el){
      if(typeof el==='string')el=document.querySelector(el);
      if(!el)return;
      el.classList.add('cc-loading');
      el.dataset._ccLoading='1';
    },
    hide(el){
      if(typeof el==='string')el=document.querySelector(el);
      if(!el)return;
      el.classList.remove('cc-loading');
      delete el.dataset._ccLoading;
    }
  };

  // ── Badge HTML ──
  function badge(text, type){
    return `<span class="cc-badge ${type||'off'}">${text}</span>`;
  }

  // ── Status dot HTML ──
  function dot(online){
    return `<span class="cc-dot ${online?'on':'off'}"></span>`;
  }

  // ── Skeleton placeholder ──
  function skeleton(width, height){
    return `<div class="cc-skeleton" style="width:${width||'100%'};height:${height||'18px'}"></div>`;
  }

  return {
    toast,
    fetch: guardedFetch,
    loading,
    badge,
    dot,
    skeleton,
    getToken,
  };
})();
