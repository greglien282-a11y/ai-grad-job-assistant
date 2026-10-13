/* V0.3 interaction prototype. All logic is local, deterministic and illustrative.
   No AI, authentication, resume parser, database or job-board integration. */
(() => {
  'use strict';
  const FACTS = [
    {id:'python', text:'使用 Python 编写图像处理代码', kind:'tech'},
    {id:'image', text:'完成图片读取、尺寸调整等预处理', kind:'tech'},
    {id:'labels', text:'整理图片标签与训练数据集', kind:'data'},
    {id:'split', text:'划分训练集、验证集或测试集', kind:'data'},
    {id:'train', text:'运行已有模型训练程序', kind:'model'},
    {id:'params', text:'调整 Epoch、学习率等参数', kind:'model'},
    {id:'metric', text:'查看预测结果、准确率和损失值', kind:'evaluate'},
  ];
  const JD_EXAMPLE = '计算机视觉算法实习生（示例岗位）\n岗位职责：参与图像数据清洗、模型训练及测试，协助分析识别效果。\n岗位要求：熟悉 Python；了解图像预处理；具有 PyTorch 或深度学习训练实践；了解目标检测、模型评估；具有相关项目经历。';
  const QU = [
    {q:'请简单介绍一下你参与的图像识别项目，以及你个人负责的部分。',cat:'fact',tip:'先讲任务目标，再讲亲手完成的工作。团队成果要与个人贡献分开。'},
    {q:'你当时是如何处理图像数据、整理标签的？',cat:'fact',tip:'围绕实际处理步骤回答。如果只是记不清当时的操作，应标记为待核实。'},
    {q:'Epoch 和学习率分别是什么？调整它们可能带来什么变化？',cat:'knowledge',tip:'Epoch 是训练数据被遍历的轮次；学习率影响参数更新步长。'},
    {q:'Precision 和 Recall 各代表什么？玻璃破损报警更需要关注什么？',cat:'knowledge',tip:'Precision 重在预测为正的结果有多少是真的；Recall 重在真实目标有多少被找出。'},
    {q:'离线结果很好但现场漏检变多，你会如何分层排查？',cat:'knowledge',tip:'可从数据分布、模型能力、推理阈值、部署链路逐层定位。'},
    {q:'为什么要把高度相似的连续帧按视频或场景分组划分？',cat:'knowledge',tip:'避免训练与验证出现过于相似的样本，从而高估泛化能力。'},
    {q:'实例分割的 Mask 与类别标签有什么区别？',cat:'knowledge',tip:'Mask 表示对象像素区域；类别标签说明属于哪一类。'},
    {q:'你如何确认 mAP50、mAP50-95 来自哪个数据集以及 Box 还是 Mask？',cat:'fact',tip:'需要核对实验日志和评估结果；不能凭记忆创造评价口径。'},
    {q:'如果部署后出现大量误报，调整置信度阈值会怎样影响 Precision 和 Recall？',cat:'knowledge',tip:'一般更高阈值有助于过滤低置信度预测，但会有召回下降风险。'}
  ];
  const pageNames={home:'首页',space:'我的空间',import:'导入已有简历',mine:'AI 经历挖掘',job:'目标岗位分析',resume:'定制简历',interview:'模拟面试',report:'练习复盘'};
  const el = (id)=>document.getElementById(id);
  const escape=(str)=>String(str??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const initial=()=>({page:'home',mineText:'基于 Python 完成了一个图像识别课程设计。',importText:'',mineStage:0,mineChoices:[],confirmed:[],jobText:JD_EXAMPLE,jobAnalyzed:false,resumeSaved:false,mode:'quick',interview:{active:false,idx:0,answers:[],feedback:null,finished:false},autoShowResume:true});
  let S=initial();
  let toastTimer;
  function toast(msg){const t=el('toast');t.textContent=msg;t.classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('visible'),2500)}
  function has(id){return S.confirmed.includes(id)}
  function nav(page){closeFlow();closeAccount();S.page=page;render();window.scrollTo({top:0,behavior:'smooth'})}
  function getFacts(){return FACTS.filter(f=>has(f.id))}
  function projectBullets(){
    const arr=[];
    if(has('python')||has('image')||has('labels')||has('split')){const parts=[];
      if(has('python'))parts.push('使用 Python 编写图像处理代码');
      if(has('image'))parts.push('完成图片读取与基础预处理');
      if(has('labels'))parts.push('整理图像标签及数据集');
      if(has('split'))parts.push('划分训练、验证或测试数据');
      arr.push({name:'数据处理',desc:parts.join('，')+'。',ids:['python','image','labels','split'].filter(has)});
    }
    if(has('train')||has('params')){const parts=[];
      if(has('train'))parts.push('基于已有模型训练程序开展实验');
      if(has('params'))parts.push('调整训练轮数与学习率等超参数');
      arr.push({name:'训练实践',desc:parts.join('，')+'。',ids:['train','params'].filter(has)});
    }
    if(has('metric'))arr.push({name:'效果观察',desc:'查看模型预测结果、准确率及损失值等指标，观察识别效果。',ids:['metric']});
    return arr;
  }
  function render(){
    const p=S.page;
    el('app').classList.toggle('is-landing',p==='home');
    el('page-crumb').textContent=p==='home'?'':pageNames[p]||'首页';
    const html=({home,space,import:importPage,mine,job,resume,interview,report}[p]||home)();
    el('view').innerHTML=html;
  }
  function pathline(active){const steps=[['mine','经历挖掘'],['job','目标岗位'],['resume','定制简历'],['interview','面试复习']];return '<div class="pathline">'+steps.map((v,i)=>`${i?' <span style="background:transparent;border:0;padding:0">→</span> ':''}${v[0]===active?`<strong>${v[1]}</strong>`:`<span>${v[1]}</span>`}`).join('')+'</div>'}
  function home(){return `
    <section class="landing-screen" aria-labelledby="landing-title">
      <div class="ambient" aria-hidden="true"><span class="glow glow-one"></span><span class="glow glow-two"></span><span class="glow glow-three"></span><span class="glow glow-four"></span><span class="ambient-grid"></span></div>
      <div class="landing-center">
        <div class="landing-kicker"><span class="kicker-star">✦</span> A BETTER START, WITH AI <span class="kicker-star">✦</span></div>
        <h1 id="landing-title">你的经历，<br/><span>值得被更好地看见。</span></h1>
        <p class="landing-subtitle">从挖掘真实经历，到针对岗位优化简历，再到自信应对面试。<br class="desktop-only"/>下一步，从最适合你的地方开始。</p>
        <div class="landing-choices" aria-label="选择你的求职起点">
          <button class="landing-choice" data-nav="import"><span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3.5h7l4 4v13H7a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z"/><path d="M14 3.5v4h4M9 12h6M9 16h5"/></svg></span><span class="choice-content"><strong>我已经有简历了</strong><span>整理已有内容，让你的优势被看见</span></span><span class="choice-go" aria-hidden="true">↗</span></button>
          <button class="landing-choice" data-nav="mine"><span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 1.9 6.1L20 11l-6.1 1.9L12 19l-1.9-6.1L4 11l6.1-1.9L12 3Z"/><path d="m19 17 .65 1.35L21 19l-1.35.65L19 21l-.65-1.35L17 19l1.35-.65L19 17Z"/></svg></span><span class="choice-content"><strong>我还没有像样的简历</strong><span>从真实经历出发，找到属于你的亮点</span></span><span class="choice-go" aria-hidden="true">↗</span></button>
          <button class="landing-choice" data-nav="job"><span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/></svg></span><span class="choice-content"><strong>我已经找到目标岗位</strong><span>读懂岗位要求，找到更合适的表达</span></span><span class="choice-go" aria-hidden="true">↗</span></button>
        </div>
        <button type="button" class="flow-link" data-action="open-flow"><span class="flow-link-icon">?</span> 还不确定从哪里开始？了解完整流程 <span aria-hidden="true">→</span></button>
      </div>
      <div class="landing-corner" aria-hidden="true">MAKE YOUR NEXT MOVE COUNT <span>·</span> 01 / 03</div>
    </section>`}
  function space(){return `<div class="space-heading"><div class="eyebrow">YOUR SPACE / 体验工作台</div><h1>欢迎回到你的求职空间。</h1><p>从这里继续整理经历、定制岗位简历或复习面试。当前是访客演示，刷新页面后进度不会保留。</p></div>
    <div class="space-summary"><div class="space-stat"><span>已确认的经历事实</span><strong>${S.confirmed.length}</strong><small>来自当前会话的自述</small></div><div class="space-stat"><span>候选简历版本</span><strong>${S.resumeSaved?'1':'0'}</strong><small>仅供交互演示</small></div><div class="space-stat"><span>模拟面试回答</span><strong>${S.interview.answers.length}</strong><small>尚未进行智能评分</small></div></div>
    <div class="space-section-heading"><h2>继续你的求职准备</h2><button class="space-home-link" data-nav="home">返回三个入口 ↗</button></div>
    <div class="space-modules">
      <button class="space-module" data-nav="mine"><span class="space-module-icon">✧</span><strong>我的经历库</strong><span>继续挖掘和确认真实项目经历</span><i>↗</i></button>
      <button class="space-module" data-nav="resume"><span class="space-module-icon">▤</span><strong>我的简历</strong><span>查看候选表达与针对岗位的版本</span><i>↗</i></button>
      <button class="space-module" data-nav="job"><span class="space-module-icon">◎</span><strong>岗位定制</strong><span>针对目标岗位分析匹配与能力差距</span><i>↗</i></button>
      <button class="space-module" data-nav="interview"><span class="space-module-icon">◉</span><strong>面试训练</strong><span>3 题快速复习 / 5 题标准模拟 / 深度练习</span><i>↗</i></button>
      <button class="space-module" data-nav="report"><span class="space-module-icon">▥</span><strong>练习复盘</strong><span>查看待核实事实与待复习知识</span><i>↗</i></button>
    </div>
    <div class="space-note"><strong>演示说明</strong><p>此个人空间仅模拟已使用用户的回访入口。尚无真实账号、登录、数据库或跨会话保存；系统不会把模拟数据当作个人真实资料。</p></div>`}
  function importPage(){return `<div class="page-heading"><div class="eyebrow">FIRST STEP · PATH A</div><h1>已有简历？从整理现有内容开始</h1><p>当前仅展示「粘贴简历文本」的交互；PDF/DOCX 上传及自动解析尚未实现。</p></div>${pathline('mine')}
    <div class="layout-main-side"><section class="card card-pad"><label class="input-label" for="import-text">粘贴现有简历或项目描述</label><textarea id="import-text" class="field" style="min-height:220px" placeholder="粘贴项目经历、技能等内容。我们会保留原文，等待你确认相关事实。">${escape(S.importText)}</textarea><p class="help">此版本不使用 AI 自动解析；后续会让你通过经历挖掘确认可用于简历的事实。</p><div class="separator"></div><div class="button-row"><button class="btn" data-action="import-next">继续整理真实经历 →</button><button class="btn secondary" data-nav="home">返回首页</button></div></section>
    <aside class="card card-pad"><div class="badge-heading"><h3>真实性原则</h3><span class="pill green">先核实</span></div><div class="point"><span class="pointicon">✓</span><span>保留用户原始表达与已确认信息</span></div><div class="point"><span class="pointicon">✓</span><span>模糊职责和成果必须核实</span></div><div class="point"><span class="pointicon">✓</span><span>简历可优化表达，但不编造经历</span></div></aside></div>`}
  function mine(){const choiceHtml=FACTS.map(f=>`<button class="choice ${S.mineChoices.includes(f.id)?'selected':''}" data-choice="${f.id}" aria-pressed="${S.mineChoices.includes(f.id)}">${escape(f.text)}</button>`).join('');
    let main='';
    if(S.mineStage===0)main=`<div class="badge-heading"><h3>先说一件你真实做过的事</h3><span class="pill">第 1 步</span></div><label class="input-label" for="mine-text">不必使用专业术语，想到什么写什么</label><textarea class="field" id="mine-text" style="min-height:140px" placeholder="例如：我本科做过一个 Python 图像识别课程设计……">${escape(S.mineText)}</textarea><p class="help">这里使用图像识别课程设计作为可编辑的演示案例。</p><div class="separator"></div><button class="btn" data-action="mine-start">开始梳理经历 →</button>`;
    if(S.mineStage===1)main=`<div class="badge-heading"><h3><span class="number">1</span>你当时亲手做过哪些事情？</h3><span class="pill">可多选</span></div><p style="font-size:12px">为了避免 AI 诱导回忆，只选择你能确认做过的项目。没印象的项目不用勾选。</p><div class="choice-grid">${choiceHtml}</div><div class="separator"></div><div class="button-row"><button class="btn" data-action="mine-review">整理候选事实 →</button><button class="btn secondary" data-action="mine-skip">跳过追问</button></div>`;
    if(S.mineStage===2)main=`<div class="badge-heading"><h3><span class="number">2</span>请确认：这些内容真的做过吗？</h3><span class="pill amber">等待你的确认</span></div><p style="font-size:12px">下方仅来自你刚刚的选择。确认后才作为「用户自述事实」保存，仍不等于代码或报告核验。</p><div class="result-group">${S.mineChoices.length?S.mineChoices.map(id=>{const f=FACTS.find(x=>x.id===id);return `<div class="item"><span class="symbol ok">◉</span><div><b>${escape(f.text)}</b><p>来源：本次勾选 · 等待确认</p></div></div>`}).join(''):'<div class="item">未选择任何具体工作，可以返回继续补充。</div>'}</div><div class="separator"></div><div class="button-row"><button class="btn" data-action="mine-confirm" ${S.mineChoices.length?'':'disabled'}>确认这些事实并生成候选表达 →</button><button class="btn secondary" data-action="mine-back">返回修改</button></div>`;
    if(S.mineStage===3)main=`<div class="badge-heading"><h3>你的第一张项目经历卡</h3><span class="pill green">已自述确认</span></div><div class="soft-panel green"><strong style="font-size:13px">✓ 我们找到 ${S.confirmed.length} 项真实工作线索</strong><p>已按你的确认记录，不自动增加框架、模型名称、指标和成果。</p></div><div style="margin:22px 0 10px"><span class="live-label">原始描述</span><div class="resume-line before">${escape(S.mineText)}</div></div><span class="live-label">专业候选表达（本地规则拼接示例）</span>${projectBullets().map(x=>`<div class="resume-line after"><strong>${x.name}：</strong>${escape(x.desc)}</div>`).join('')||'<div class="empty-state">暂无可以使用的候选表达</div>'}<div class="button-row" style="margin-top:23px"><button class="btn" data-nav="job">拿这段经历匹配岗位 →</button><button class="btn secondary" data-nav="resume">预览简历</button><button class="btn secondary" data-action="mine-edit">继续补充事实</button></div>`;
    return `<div class="page-heading"><div class="eyebrow">AI EXPERIENCE MINING · PATH B</div><h1>你做过的事情，比一句话更多</h1><p>少量追问、明确核实、随时结束。先找到事实，再谈有竞争力的表达。</p></div>${pathline('mine')}<div class="layout-main-side"><section class="card card-pad">${main}</section><aside class="card card-pad"><div class="badge-heading"><h3>真实经历档案</h3><span class="pill gray">持续积累</span></div><div class="timeline"><span class="dot done"></span><span class="dot ${S.mineStage>0?'done':''}"></span><span class="dot ${S.mineStage>1?'done':''}"></span><span class="dot ${S.mineStage>2?'done':''}"></span><small class="muted">记录 → 追问 → 确认 → 表达</small></div><div class="soft-panel"><strong style="font-size:12px">这不是自动编写你的故事</strong><p>你勾选的内容仍需本人确认。尚未确认的能力、工具、性能指标不会进入简历。</p></div><div class="separator"></div><h3 style="margin-bottom:7px;font-size:13px">已确认的事实</h3>${getFacts().length?getFacts().map(f=>`<div class="fact-item">• ${escape(f.text)} <span>自述</span></div>`).join(''):'<div class="empty-state">尚未确认具体经历。\n完成一次追问后将显示在这里。</div>'}<div class="separator"></div><span class="pill amber">待核实 ≠ 不会</span><p style="font-size:11px;margin:10px 0 0">实验指标、具体模型、团队职责都需要额外证据或本人明确说明。</p></aside></div>`;
  }
  function job(){const matched=[['Python 编程实践',has('python')?'有用户自述依据':'尚无确认依据',has('python')?'ok':'maybe'],['图像处理与数据准备',has('image')||has('labels')?'有用户自述依据':'尚无确认依据',has('image')||has('labels')?'ok':'maybe'],['模型训练实践',has('train')?'有用户自述依据':'尚无确认依据',has('train')?'ok':'maybe'],['PyTorch 实际使用', '尚无确认依据','maybe'],['目标检测 / YOLO 知识','尚无确认依据','maybe']];
    return `<div class="page-heading"><div class="eyebrow">JOB STRATEGY · PATH C</div><h1>先判断岗位要求，再决定怎样改简历</h1><p>不是每份简历都要强行改。优先匹配真实事实，指出尚未得到证据支持的要求。</p></div>${pathline('job')}<div class="layout-main-side"><section class="card card-pad"><div class="badge-heading"><h3>粘贴目标岗位 JD</h3><span class="pill gray">示例岗位</span></div><textarea id="jd-text" class="field" style="min-height:198px">${escape(S.jobText)}</textarea><p class="help">这是本地交互演示：使用预设岗位要求核对已确认经历，不包含实时岗位搜索或 AI 语义解析。</p><div class="button-row" style="margin-top:18px"><button class="btn" data-action="job-analyze">查看岗位匹配策略 →</button><button class="btn secondary" data-action="job-example">恢复示例 JD</button></div>${S.jobAnalyzed?`<div class="separator"></div><div class="badge-heading"><h3>岗位匹配解释</h3><span class="pill amber">规则演示 · 非真实 AI 结论</span></div><p style="font-size:12px">基于示例「计算机视觉算法实习生」的预设要求，与本次已确认事实进行对照；若您修改了 JD，本原型不会自动提取新的要求。</p><div class="result-group">${matched.map(([title,note,status])=>`<div class="item"><span class="symbol ${status}">${status==='ok'?'✓':'◌'}</span><div><b>${title}</b><p>${note}${status==='maybe'?' · 不能直接补写到简历':''}</p></div></div>`).join('')}</div><div class="soft-panel amber" style="margin-top:17px"><b style="font-size:12px">关键提醒</b><p>没有提到 PyTorch ≠ 一定不会。若确实没有相关实践，应如实保留能力差距；若做过，可返回经历档案补充并确认。</p></div><div class="button-row" style="margin-top:20px"><button class="btn" data-nav="resume">查看岗位专属候选简历 →</button><button class="btn secondary" data-nav="mine">补充事实</button></div>`:''}</section><aside class="card card-pad"><div class="badge-heading"><h3>岗位定制原则</h3><span class="pill green">一岗一策略</span></div><div class="point"><span class="pointicon">①</span><span>先判断有哪些已确认的相关经历</span></div><div class="point"><span class="pointicon">②</span><span>区分「会但没写好」和「确实尚未掌握」</span></div><div class="point"><span class="pointicon">③</span><span>简历强调相关事实，不虚构岗位需要的技能</span></div><div class="separator"></div><h3 style="font-size:13px">目前可用的个人事实</h3><div class="fact-list">${getFacts().length?getFacts().map(f=>`<span class="fact good">${escape(f.text)}</span>`).join(''):'<span class="fact warn">暂无确认事实，可先输入 JD 再补充</span>'}</div></aside></div>`;
  }
  function resume(){const bullets=projectBullets();return `<div class="page-heading"><div class="eyebrow">TAILORED RESUME · V0.3</div><h1>写得更专业，但只写真实的你</h1><p>保留原始描述、修改理由和事实来源。岗位定制不是无中生有。</p></div>${pathline('resume')}<div class="layout-main-side"><section class="card card-pad"><div class="badge-heading"><h3>岗位专属简历 · 候选预览</h3><span class="pill ${S.resumeSaved?'green':'amber'}">${S.resumeSaved?'已存为演示版本':'等待确认'}</span></div><div class="cv"><div class="cv-head"><h2>示例同学</h2><small>应届生 · 计算机视觉 / Python 相关岗位｜演示简历（非真实个人资料）</small></div><div class="cv-section"><h4>项目经历</h4><strong style="font-size:13px">基于 Python 的图像识别课程设计</strong><p>项目定位：图像数据处理与模型训练实践（用户自述）</p>${bullets.length?`<ul>${bullets.map(b=>`<li><b>${b.name}：</b>${escape(b.desc)}</li>`).join('')}</ul>`:'<div class="empty-state" style="margin:13px 0">还没有已确认的项目事实。请先完成经历挖掘，再生成候选表述。</div>'}</div><div class="cv-section"><h4>技能与补充说明</h4><p>${has('python')?'Python（图像处理代码实践）':'暂无已确认的编程技能'}；其余技能需用户补充实际经历后确认。</p></div><div class="cv-section"><h4>真实性提示</h4><p>本卡片仅演示内容布局。未收集真实姓名、学校、日期、获奖与成果指标，不能直接作为可投递简历。</p></div></div><div class="button-row" style="margin-top:20px"><button class="btn" data-action="save-resume" ${bullets.length?'':'disabled'}>${S.resumeSaved?'✓ 已保存演示版本':'确认并保存这个候选版本'}</button><button class="btn secondary" data-action="copy-resume" ${bullets.length?'':'disabled'}>复制项目表述</button></div><p class="help">此原型暂不提供正式 PDF 导出、模板排版或云端版本管理。</p></section><aside class="card card-pad"><div class="badge-heading"><h3>为什么这样修改？</h3><span class="pill green">可追溯</span></div><span class="live-label">原始表述</span><div class="resume-line before">${escape(S.mineText)}</div><span class="live-label">岗位相关表达</span>${bullets.length?bullets.map(b=>`<div class="resume-line after"><b>${b.name}</b>：${escape(b.desc)}<p style="font-size:10px;margin:5px 0 0">依据：用户确认的 ${b.ids.length} 条事实</p></div>`).join(''):'<div class="empty-state">尚无可供改写的真实事实</div>'}<div class="separator"></div><div class="soft-panel green"><strong style="font-size:12px">不额外添加</strong><p>未确认的框架、准确率、算法创新、独立部署与量化成果。</p></div><div class="separator"></div><h3 style="font-size:13px">简历准备好了，面试呢？</h3><p style="font-size:12px">花约 5 分钟复习项目，检测是否能解释自己写在简历里的工作。</p><button class="btn ghost" data-nav="interview">帮我掌握这份简历 →</button></aside></div>`}
  function interview(){const I=S.interview;
    const modes=[['quick','⚡','快速复习','3 道核心题 · 约 5 分钟'],['standard','◎','标准模拟','5 道进阶题 · 约 10–15 分钟'],['deep','✦','深度拷打','逐步深入 · 示例题库 9 题']];
    const modeHtml=modes.map(([id,icon,title,sub])=>`<button class="mode-card ${S.mode===id?'selected':''}" data-mode="${id}" aria-pressed="${S.mode===id}"><span class="modeicon">${icon}</span><strong>${title}</strong><p>${sub}</p></button>`).join('');
    const questions=S.mode==='quick'?[QU[0],QU[1],QU[2]]:S.mode==='standard'?[QU[0],QU[2],QU[3],QU[4],QU[5]]:QU;
    let body='';
    if(!I.active && !I.finished)body=`<div class="badge-heading"><h3>选择练习强度</h3><span class="pill green">默认快速复习</span></div><div class="grid3">${modeHtml}</div><div class="soft-panel" style="margin:20px 0"><strong style="font-size:12px">本原型的面试反馈为规则演示</strong><p>不进行 AI 语义理解或真实评分，不会因为「记不清」就断定技术不会。可随时结束并查看复盘。</p></div><button class="btn" data-action="interview-start">开始${S.mode==='quick'?'快速复习':S.mode==='standard'?'标准模拟':'深度拷打'} →</button>`;
    else if(I.finished)body=`<div class="soft-panel green" style="margin-bottom:20px"><strong>本轮练习已结束</strong><p>练习记录已整理，可以直接查看复盘，或选择其他模式重新开始。</p></div><div class="button-row"><button class="btn" data-nav="report">查看本轮复盘 →</button><button class="btn secondary" data-action="interview-restart">重新练习</button></div>`;
    else {const q=questions[I.idx];body=`<div class="badge-heading"><h3>模拟面试 · ${S.mode==='quick'?'快速复习':S.mode==='standard'?'标准模拟':'深度拷打'}</h3><span class="pill">${I.idx+1} / ${questions.length} 题</span></div><div class="timeline">${questions.map((_,n)=>`<span class="dot ${n<=I.idx?'done':''}"></span>`).join('')}</div><div class="soft-panel"><span class="q-step">面试官 · 第 ${I.idx+1} 题</span><div class="q-title">${escape(q.q)}</div><span class="pill ${q.cat==='fact'?'amber':'gray'}">${q.cat==='fact'?'项目事实与表达':'技术知识与分析'}</span></div>${I.feedback?`<div class="feedback"><h4>${I.feedback==='known'?'已记录本轮作答':I.feedback==='verify'?'已标记为：历史细节待核实':'已标记为：技术知识待学习'}</h4><p>${I.feedback==='known'?'这是演示反馈：系统记录了你的回答，但没有 AI 语义理解能力，因此不能判断回答是否准确。':I.feedback==='verify'?'无需猜测当年的操作或指标。建议回看代码、配置文件或实验报告。':'可以先学习这道题的相关知识，然后再验证自己的理解。'}</p><p><b>参考要点：</b>${escape(q.tip)}</p><div class="button-row" style="margin-top:14px"><button class="btn" data-action="interview-next">${I.idx===questions.length-1?'完成练习并生成复盘':'下一题 →'}</button><button class="btn secondary" data-action="interview-end">现在结束并复盘</button></div></div>`:`<label class="input-label" for="interview-answer" style="margin-top:21px">你的回答</label><textarea id="interview-answer" class="field" style="min-height:130px" placeholder="像真实面试一样说出来，也可以直接选择下方的状态……"></textarea><div class="button-row" style="margin-top:13px"><button class="btn" data-action="interview-answer">提交回答</button><button class="btn secondary" data-action="interview-unknown">${q.cat==='fact'?'记不清历史细节':'这个知识点我不会'}</button><button class="btn secondary" data-action="interview-skip">跳过</button></div><p class="help">示例版本：提交后仅展示参考要点，不使用算法自动评分。</p>`}<div class="separator"></div><button class="btn secondary small" data-action="interview-end">结束面试并生成报告</button>`}
    return `<div class="page-heading"><div class="eyebrow">MASTER YOUR RESUME · STEP 3</div><h1>简历写好了，也要讲得清楚</h1><p>不只是获得一份漂亮简历，还要能够解释它为什么真实、技术原理是什么。</p></div>${pathline('interview')}<section class="card card-pad">${body}</section>`;
  }
  function report(){const A=S.interview.answers;const n=A.length;const known=A.filter(x=>x.status==='known').length,verify=A.filter(x=>x.status==='verify').length,learn=A.filter(x=>x.status==='learn').length,skip=A.filter(x=>x.status==='skip').length;
    return `<div class="page-heading"><div class="eyebrow">INTERVIEW REVIEW · LEARNING RECORD</div><h1>每一次回答，都能成为下一次的准备</h1><p>分开记录「真实事实待核实」和「技术知识待学习」，不把面试生成内容冒充真实项目经历。</p></div>${n?`<div class="grid3"><div class="card stat"><div class="stat-num">${n}</div><p>完成的面试轮次（演示）</p></div><div class="card stat"><div class="stat-num">${verify}</div><p>历史事实待核实</p></div><div class="card stat"><div class="stat-num">${learn}</div><p>技术知识待学习</p></div></div><div class="grid2" style="margin-top:20px"><section class="card card-pad"><div class="badge-heading"><h3>本轮练习记录</h3><span class="pill gray">无自动评分</span></div>${A.map((a,i)=>`<div class="fact-item"><div><b>${i+1}. ${escape(a.q)}</b></div><div style="margin-top:7px"><span class="pill ${a.status==='verify'?'amber':a.status==='learn'?'amber':a.status==='known'?'green':'gray'}">${({known:'已作答（未自动核验）',verify:'事实待核实',learn:'知识待学习',skip:'已跳过'})[a.status]}</span></div>${a.text?`<p style="font-size:11px;margin:8px 0 0">你的回答：${escape(a.text)}</p>`:''}</div>`).join('')}</section><aside class="card card-pad"><div class="badge-heading"><h3>下一步行动</h3><span class="pill green">建议</span></div><div class="point"><span class="pointicon">✓</span><span>已作答 ${known} 题：可人工回看并复核表述</span></div><div class="point"><span class="pointicon">◌</span><span>历史细节 ${verify} 项：寻找代码、报告或配置资料核实</span></div><div class="point"><span class="pointicon">✎</span><span>知识薄弱点 ${learn} 项：先复习，再尝试回答类似问题</span></div><div class="point"><span class="pointicon">→</span><span>跳过 ${skip} 题：有空时可再练习</span></div><div class="separator"></div><p style="font-size:11px">这份报告不评定你实际掌握了多少知识；需要未来的 AI 面试引擎和人工验证规则才能给出可靠诊断。</p><button class="btn" data-action="interview-restart">开启新一轮练习 →</button></aside></div>`:`<section class="card report-empty"><div class="illustration">▥</div><h2>你的面试复盘还在等待第一道题</h2><p>完成一次快速复习或模拟面试后，这里会沉淀回答、待核实事实与复习建议。</p><button class="btn" data-nav="interview">开始 3 题快速复习 →</button></section>`}`;
  }
  function saveAnswer(status){const I=S.interview;const qq=(S.mode==='quick'?[QU[0],QU[1],QU[2]]:S.mode==='standard'?[QU[0],QU[2],QU[3],QU[4],QU[5]]:QU)[I.idx];
    const text=el('interview-answer')?.value?.trim()||'';
    if(status==='known'&&!text){toast('先输入回答，或者直接选择「不知道 / 跳过」');return}
    I.answers.push({q:qq.q,cat:qq.cat,text:status==='known'?text:'',status});I.feedback=status;render();}
  async function copy(text){try{if(navigator.clipboard&&location.protocol!=='file:')await navigator.clipboard.writeText(text);else{const field=document.createElement('textarea');field.value=text;document.body.appendChild(field);field.select();document.execCommand('copy');field.remove()}toast('已复制到剪贴板')}catch{toast('复制失败，请手动选择文字复制')}}
  function handle(action){switch(action){
    case 'import-next':{S.importText=el('import-text')?.value.trim()||'';if(!S.importText){toast('请先粘贴简历内容');return}S.mineText=S.importText.slice(0,800);S.mineStage=0;nav('mine');toast('已保留原文，下一步需逐项确认事实');break}
    case 'mine-start':{S.mineText=el('mine-text')?.value.trim()||'';if(!S.mineText){toast('先写下一句项目经历');return}S.mineStage=1;render();break}
    case 'mine-review':case 'mine-skip':S.mineStage=2;render();break;
    case 'mine-confirm':{S.confirmed=[...S.mineChoices];S.mineStage=3;S.resumeSaved=false;render();toast('候选事实已按你的确认保存到本次演示');break}
    case 'mine-back':S.mineStage=1;render();break;
    case 'mine-edit':S.mineStage=1;S.mineChoices=[...S.confirmed];render();break;
    case 'job-example':S.jobText=JD_EXAMPLE;S.jobAnalyzed=false;render();break;
    case 'job-analyze':S.jobText=el('jd-text')?.value.trim()||'';if(!S.jobText){toast('请先粘贴一份岗位描述');return}S.jobAnalyzed=true;render();break;
    case 'save-resume':S.resumeSaved=true;render();toast('演示版本已保存（仅保留在当前页面内存）');break;
    case 'copy-resume':copy('基于 Python 的图像识别课程设计\n'+projectBullets().map(b=>'• '+b.name+'：'+b.desc).join('\n'));break;
    case 'interview-start':S.interview={active:true,idx:0,answers:[],feedback:null,finished:false};render();break;
    case 'interview-answer':saveAnswer('known');break;
    case 'interview-unknown':{const qq=(S.mode==='quick'?[QU[0],QU[1],QU[2]]:S.mode==='standard'?[QU[0],QU[2],QU[3],QU[4],QU[5]]:QU)[S.interview.idx];saveAnswer(qq.cat==='fact'?'verify':'learn');break}
    case 'interview-skip':saveAnswer('skip');break;
    case 'interview-next':{const limit=S.mode==='quick'?3:S.mode==='standard'?5:QU.length;S.interview.idx++;S.interview.feedback=null;if(S.interview.idx>=limit){S.interview.active=false;S.interview.finished=true;nav('report')}else render();break}
    case 'interview-end':S.interview.active=false;S.interview.finished=true;nav('report');break;
    case 'interview-restart':S.interview={active:false,idx:0,answers:[],feedback:null,finished:false};nav('interview');break;
  }}
  let lastDialogFocus=null;
  function closeAccount(){const menu=el('account-menu'),trigger=el('account-trigger');if(menu){menu.hidden=true;trigger?.setAttribute('aria-expanded','false')}}
  function toggleAccount(){const menu=el('account-menu'),trigger=el('account-trigger');const next=menu.hidden;menu.hidden=!next;trigger.setAttribute('aria-expanded',String(next));if(next)menu.querySelector('[role="menuitem"]')?.focus()}
  function openFlow(){lastDialogFocus=document.activeElement;closeAccount();el('flow-overlay').hidden=false;document.body.classList.add('dialog-open');el('flow-dialog').querySelector('.flow-close')?.focus()}
  function closeFlow(){const wasOpen=!el('flow-overlay').hidden;el('flow-overlay').hidden=true;document.body.classList.remove('dialog-open');if(wasOpen&&lastDialogFocus?.isConnected)lastDialogFocus.focus()}
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){if(!el('flow-overlay').hidden){closeFlow();return}closeAccount()}
    if(e.key==='Tab'&&!el('flow-overlay').hidden){const focusables=[...el('flow-dialog').querySelectorAll('button:not([disabled])')];const first=focusables[0],last=focusables[focusables.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}
  });
  document.addEventListener('click',e=>{
    if(e.target.closest('#account-trigger')){toggleAccount();return}
    if(!e.target.closest('.account-anchor'))closeAccount();
    if(e.target.closest('#reset-demo')){if(confirm('重置当前浏览器中的演示状态？此操作不会修改 GitHub 仓库。')){S=initial();nav('home');toast('演示数据已重置')}return}
    const choice=e.target.closest('[data-choice]');if(choice){const id=choice.dataset.choice;S.mineChoices=S.mineChoices.includes(id)?S.mineChoices.filter(x=>x!==id):[...S.mineChoices,id];render();return}
    const mode=e.target.closest('[data-mode]');if(mode){S.mode=mode.dataset.mode;render();return}
    const action=e.target.closest('[data-action]');if(action){if(action.dataset.action==='open-flow')openFlow();else if(action.dataset.action==='close-flow')closeFlow();else handle(action.dataset.action);return}
    const page=e.target.closest('[data-nav]');if(page)nav(page.dataset.nav);
  });
  document.addEventListener('input',e=>{if(e.target.id==='mine-text')S.mineText=e.target.value;if(e.target.id==='import-text')S.importText=e.target.value;if(e.target.id==='jd-text')S.jobText=e.target.value});
  render();
})();
