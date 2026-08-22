const $ = (selector) => document.querySelector(selector);
const els = {
  connection: $('#connection'), modeCopy: $('#mode-copy'), runtimeMode: $('#runtime-mode'), mcpTools: $('#mcp-tools'),
  transcript: $('#transcript'), empty: $('#empty-state'), caption: $('#live-caption'),
  mic: $('#mic'), textForm: $('#text-form'), textInput: $('#text-input'), send: $('.send'),
  trace: $('#trace-list'), clear: $('#clear-trace'), latency: $('#latency'),
  picker: $('#prompt-picker'), dialog: $('#prompt-dialog'), promptSearch: $('#prompt-search'),
};

let socket;
let session = { live: false, listening: false, turnStartedAt: 0, assistantNode: null };
let recorder = null;
let playback = { context: null, nextAt: 0, sources: new Set() };
let speechBuffer = '';

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const basePath = location.pathname.endsWith('/') ? location.pathname : `${location.pathname}/`;
  socket = new WebSocket(`${protocol}//${location.host}${basePath}ws/voice`);
  socket.binaryType = 'arraybuffer';
  socket.onopen = () => setConnection('loading', '初始化中');
  socket.onclose = () => { setConnection('error', '已断开'); setTimeout(connect, 1600); };
  socket.onerror = () => setConnection('error', '连接失败');
  socket.onmessage = async (event) => {
    if (event.data instanceof ArrayBuffer) {
      try { await playPcm(event.data, 24000); }
      catch (error) { addTrace('error', '浏览器阻止了声音播放，请再次点击发送或麦克风', error.name); }
      return;
    }
    handle(JSON.parse(event.data));
  };
}

function handle(event) {
  if (event.type === 'session.ready') {
    session.live = event.speech_live;
    setConnection('success', '已连接');
    els.runtimeMode.textContent = event.agent_live ? '方舟实时' : '离线演示';
    els.mcpTools.replaceChildren(...(event.mcp_tools || []).map((name) => {
      const item = document.createElement('span'); item.textContent = name; return item;
    }));
    els.modeCopy.textContent = event.speech_live ? '豆包流式语音已就绪；按下麦克风后建立实时连接。' : event.agent_live ? '方舟 Agent 已连接；配置豆包语音 Key 后可使用麦克风。' : '当前使用离线 Agent；文字输入完整验证规划与 MCP，回答由浏览器朗读。';
  } else if (event.type === 'listening.speech_started') {
    showCaption('检测到语音…'); stopPlayback();
  } else if (event.type === 'transcript.delta') {
    showCaption(event.text);
  } else if (event.type === 'transcript.final') {
    showCaption(event.text); setTimeout(() => { els.caption.hidden = true; }, 700);
  } else if (event.type === 'turn.started') {
    session.turnStartedAt = performance.now(); speechBuffer = ''; beginTurn(event.text);
    addTrace('run', 'Agent 开始处理', event.run_id);
  } else if (event.type === 'assistant.text.delta') {
    appendAssistant(event.text); if (!session.live) browserSpeak(event.text, false);
  } else if (event.type === 'agent.plan') {
    addTrace('plan', planLabel(event.event), event.event);
  } else if (event.type === 'agent.tool') {
    addTrace('tool', toolLabel(event), event.event);
  } else if (event.type === 'assistant.audio.started') {
    addTrace('audio', '开始流式语音合成', `${event.sample_rate} Hz PCM`);
  } else if (event.type === 'turn.completed') {
    if (!session.live) browserSpeak('', true);
    addTrace('done', '回答完成', event.run_id);
    els.latency.textContent = `本轮 ${Math.round(performance.now() - session.turnStartedAt)} ms`;
    setBusy(false); els.mic.dataset.state = session.listening ? 'listening' : 'success';
    setTimeout(() => { if (!session.listening) els.mic.dataset.state = 'default'; }, 900);
  } else if (event.type === 'turn.cancelled' || event.type === 'response.cancelled') {
    addTrace('cancel', '已打断上一轮', event.reason || 'cancelled'); stopPlayback(); setBusy(false);
  } else if (event.type === 'turn.failed' || event.type === 'speech.error') {
    addTrace('error', event.message || '语音服务出错', event.type); setBusy(false); els.mic.dataset.state = 'error';
  }
}

function beginTurn(text) {
  els.empty?.remove();
  const user = document.createElement('article'); user.className = 'message message--user';
  const p = document.createElement('p'); p.textContent = text; user.append(p); els.transcript.append(user);
  const assistant = document.createElement('article'); assistant.className = 'message message--assistant';
  const label = document.createElement('small'); label.textContent = '声旅'; const answer = document.createElement('p');
  assistant.append(label, answer); els.transcript.append(assistant); session.assistantNode = answer;
  els.transcript.scrollTop = els.transcript.scrollHeight; setBusy(true);
}

function appendAssistant(text) { if (session.assistantNode) { session.assistantNode.textContent += text; els.transcript.scrollTop = els.transcript.scrollHeight; } }
function showCaption(text) { els.caption.hidden = false; els.caption.querySelector('p').textContent = text; }
function setConnection(state, text) { els.connection.dataset.state = state; els.connection.querySelector('b').textContent = text; }
function setBusy(busy) { els.send.disabled = busy; els.send.dataset.state = busy ? 'loading' : 'default'; }
function addTrace(kind, text, meta = '') {
  els.trace.querySelector('.trace__idle')?.remove(); const li = document.createElement('li'); li.dataset.kind = kind;
  const dot = document.createElement('span'); const p = document.createElement('p'); p.textContent = text;
  if (meta) { const small = document.createElement('small'); small.textContent = meta; p.append(small); }
  li.append(dot, p); els.trace.append(li); els.trace.scrollTop = els.trace.scrollHeight;
}
function planLabel(type) { return ({'plan.started':'已创建执行计划','plan.step.started':'执行计划步骤','plan.step.completed':'计划步骤完成','plan.synthesis.started':'正在综合结果','plan.completed':'执行计划完成'})[type] || '规划状态更新'; }
function toolLabel(event) {
  const names = {'weather.get_weather':'查询天气','travel.search_places':'搜索地点','travel.estimate_route':'估算路线','search.web_search':'豆包搜索','runtime.create_plan':'创建计划'};
  const state = event.event.endsWith('completed') ? '完成' : event.event.endsWith('failed') ? '失败' : '调用';
  return `${names[event.tool_name] || event.tool_name || '工具'} · ${state}`;
}

async function toggleMic() {
  if (session.listening) return stopMic();
  if (!session.live) { els.textInput.focus(); els.mic.dataset.state = 'error'; $('#input-helper').textContent = '离线模式不上传音频；请用文字输入测试。'; return; }
  try {
    stopPlayback(); await unlockPlayback(); socket.send(JSON.stringify({type:'audio.start'})); recorder = await createRecorder((pcm) => socket.readyState === 1 && socket.send(pcm));
    session.listening = true; els.mic.dataset.state = 'listening'; els.mic.setAttribute('aria-pressed', 'true'); els.mic.querySelector('.mic__label').textContent = '结束说话';
  } catch (error) { els.mic.dataset.state = 'error'; addTrace('error', '无法访问麦克风', error.name); }
}
async function stopMic() { if (recorder) await recorder.stop(); recorder = null; session.listening = false; els.mic.dataset.state = 'loading'; els.mic.setAttribute('aria-pressed', 'false'); els.mic.querySelector('.mic__label').textContent = '开始说话'; socket.send(JSON.stringify({type:'audio.commit'})); }

async function createRecorder(onPcm) {
  const stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1, echoCancellation:true, noiseSuppression:true, autoGainControl:true}});
  const context = new AudioContext();
  const code = `class PCM extends AudioWorkletProcessor{process(i){const c=i[0]?.[0];if(c)this.port.postMessage(c.slice(0));return true}}registerProcessor('pcm',PCM)`;
  const url = URL.createObjectURL(new Blob([code], {type:'text/javascript'})); await context.audioWorklet.addModule(url); URL.revokeObjectURL(url);
  const source = context.createMediaStreamSource(stream); const node = new AudioWorkletNode(context, 'pcm'); const mute = context.createGain(); mute.gain.value = 0;
  node.port.onmessage = ({data}) => onPcm(floatToPcm16(resample(data, context.sampleRate, 16000)));
  source.connect(node); node.connect(mute); mute.connect(context.destination);
  return {stop: async () => { node.disconnect(); source.disconnect(); stream.getTracks().forEach((track) => track.stop()); await context.close(); }};
}
function resample(input, from, to) { if (from === to) return input; const ratio = from / to; const out = new Float32Array(Math.floor(input.length / ratio)); for (let i=0;i<out.length;i++){const start=Math.floor(i*ratio), end=Math.min(Math.floor((i+1)*ratio),input.length); let sum=0; for(let j=start;j<end;j++)sum+=input[j]; out[i]=sum/Math.max(1,end-start);} return out; }
function floatToPcm16(input) { const out = new Int16Array(input.length); for(let i=0;i<input.length;i++){const s=Math.max(-1,Math.min(1,input[i]));out[i]=s<0?s*32768:s*32767;} return out.buffer; }

async function playPcm(buffer, sampleRate) {
  await unlockPlayback(sampleRate);
  const pcm = new Int16Array(buffer), floats = new Float32Array(pcm.length); for(let i=0;i<pcm.length;i++)floats[i]=pcm[i]/32768;
  const audio = playback.context.createBuffer(1, floats.length, sampleRate); audio.copyToChannel(floats,0); const source=playback.context.createBufferSource(); source.buffer=audio; source.connect(playback.context.destination);
  const now=playback.context.currentTime; playback.nextAt=Math.max(now+0.03,playback.nextAt); source.start(playback.nextAt); playback.nextAt+=audio.duration; playback.sources.add(source); source.onended=()=>playback.sources.delete(source);
}
async function unlockPlayback(sampleRate = 24000) {
  if (!playback.context) playback.context = new AudioContext({sampleRate});
  if (playback.context.state !== 'running') await playback.context.resume();
}
function stopPlayback() { playback.sources.forEach((source)=>{try{source.stop();}catch{}}); playback.sources.clear(); playback.nextAt=0; speechSynthesis.cancel(); speechBuffer=''; }
function browserSpeak(delta, flush) { speechBuffer += delta; const match = speechBuffer.match(/^(.+?[。！？；])/); if (match || (flush && speechBuffer.trim())) { const text = match ? match[1] : speechBuffer; speechBuffer = match ? speechBuffer.slice(text.length) : ''; const u=new SpeechSynthesisUtterance(text); u.lang='zh-CN'; u.rate=1.05; speechSynthesis.speak(u); if (flush && speechBuffer.trim()) browserSpeak('', true); } }

els.mic.addEventListener('click', toggleMic);
els.textForm.addEventListener('submit', async (event) => { event.preventDefault(); const text=els.textInput.value.trim(); if(text&&socket.readyState===1){stopPlayback();try{await unlockPlayback();}catch(error){addTrace('error','浏览器未允许声音播放',error.name);}socket.send(JSON.stringify({type:'text.submit',text}));els.textInput.value='';} });
document.addEventListener('click', (event) => { const example=event.target.closest('[data-example]'); if(example){els.textInput.value=example.dataset.example;els.textForm.requestSubmit();} });
els.clear.addEventListener('click', () => { els.trace.replaceChildren(); addTrace('idle','等待一次问题。规划、工具和总结事件会显示在这里。'); });
els.picker.addEventListener('click', () => { els.dialog.showModal(); setTimeout(()=>els.promptSearch.focus(),0); });
document.addEventListener('keydown', (event) => { if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();els.dialog.open?els.dialog.close():els.picker.click();} });
els.dialog.querySelectorAll('[data-prompt]').forEach((button)=>button.addEventListener('click',(event)=>{event.preventDefault();els.textInput.value=button.value;els.dialog.close();els.textForm.requestSubmit();}));
els.promptSearch.addEventListener('input',()=>{const q=els.promptSearch.value.trim();els.dialog.querySelectorAll('[data-prompt]').forEach((b)=>b.hidden=!b.textContent.includes(q));});
connect();
