// ===== IT Control JS — API-based operations console =====

let currentUserId = null;
let stickyColor = 'yellow';
let editingUserData = null;

// ======== UTILS ========
function showMsg(msg, type = 'info') {
    const area = document.getElementById('messageArea');
    const el = document.createElement('div');
    el.className = `message ${type}`;
    el.textContent = msg;
    area.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

function fecharModal(id) { document.getElementById(id).style.display = 'none'; }
function abrirModal(id) { document.getElementById(id).style.display = 'flex'; }
function copiar(id) {
    const v = document.getElementById(id).value;
    navigator.clipboard.writeText(v).then(() => showMsg('✅ Copiado!', 'success'));
}

async function api(url, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    if (!r.ok) {
        const err = await r.json().catch(() => ({ error: r.statusText }));
        throw new Error(err.error || r.statusText);
    }
    return r.json();
}

function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso + 'T00:00');
    return d.toLocaleDateString('pt-BR');
}

function certStatus(validade) {
    if (!validade) return '';
    const diff = (new Date(validade) - new Date()) / 86400000;
    if (diff < 0) return '<span class="badge-expired">❌ Expirado</span>';
    if (diff < 30) return '<span class="badge-expiring">⚠️ Expira em breve</span>';
    return '<span class="badge-ok">✅ Válido</span>';
}

function revisaoStatus(data_ultima) {
    if (!data_ultima) return '<span class="badge-expired">⚠️ Nunca revisada</span>';
    const diff = (new Date() - new Date(data_ultima)) / 86400000;
    if (diff > 90) return '<span class="badge-expiring">⚠️ > 90 dias</span>';
    return '<span class="badge-ok">✅ Em dia</span>';
}

function statusBadge(status) {
    const map = {
        'Ativo': 'badge-ok', 'Em Uso': 'badge-ok', 'Concluída': 'badge-ok',
        'Inativo': 'badge-expiring', 'Manutenção': 'badge-expiring',
        'Demitido': 'badge-expired', 'Descartado': 'badge-expired', 'Disponível': 'badge-info'
    };
    return `<span class="${map[status] || 'badge-info'}">${status}</span>`;
}

// ======== TABS ========
function switchTab(tab) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    const content = document.getElementById('tab-' + tab);
    const btn = document.querySelector(`[data-tab="${tab}"]`);
    if (content) content.classList.add('active');
    if (btn) btn.classList.add('active');

    // Hide user panel if going away
    const panel = document.getElementById('userPanel');
    if (tab !== 'usuarios') {
        panel.classList.add('hidden');
        document.getElementById('tab-usuarios').classList.remove('hidden');
    }

    // Load data for the tab
    const loaders = {
        dashboard: carregarDashboard,
        usuarios: carregarUsuarios,
        ativos: carregarAtivos,
        certificados: carregarCertificadosGlobal,
        'emails-global': carregarEmailsGlobal,
        nas: carregarNASPastas,
        programas: carregarProgramasGlobal,
        contas: carregarContasGlobal,
        auditoria: carregarAuditoria,
        notas: carregarSticky,
        ia: () => { /* Chat interativo */ }
    };
    if (loaders[tab]) loaders[tab]();
}

function switchSubtab(sub) {
    document.querySelectorAll('.subtab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('subtab-' + sub).classList.add('active');
    document.querySelector(`[data-subtab="${sub}"]`).classList.add('active');

    const loaders = {
        pc: carregarPanelPC,
        contas_user: carregarPanelContas,
        emails_user: carregarPanelEmails,
        nas_user: carregarPanelNAS,
        certs_user: carregarPanelCerts,
        progs_user: carregarPanelProgs,
    };
    if (loaders[sub]) loaders[sub]();
}

// ======== INIT ========
document.addEventListener('DOMContentLoaded', () => {
    carregarUsuarioSessao();
    carregarDashboard();

    document.querySelectorAll('.modal').forEach(m => {
        m.addEventListener('click', e => { if (e.target === m) m.style.display = 'none'; });
    });
});

async function carregarUsuarioSessao() {
    try {
        const d = await api('/usuario');
        document.getElementById('username').textContent = d.usuario;
        document.getElementById('userAvatar').textContent = d.usuario[0].toUpperCase();
    } catch { }
}

// ======== DASHBOARD ========
async function carregarDashboard() {
    try {
        const stats = await api('/api/it/stats');
        document.getElementById('kpi-users').textContent = stats.usuarios_ativos;
        document.getElementById('kpi-pcs').textContent = stats.pcs_em_uso;
        document.getElementById('kpi-manutencao').textContent = stats.pcs_manutencao;
        document.getElementById('kpi-certs-exp').textContent = stats.certs_expirados;
        document.getElementById('kpi-certs-30').textContent = stats.certs_expirando_30;
        document.getElementById('kpi-revisao').textContent = stats.contas_sem_revisao;
    } catch (e) { console.error('Dashboard stats error:', e); }

    try {
        const users = await api('/api/it/users?status=Ativo');
        const mini = document.getElementById('dashRecentUsers');
        mini.innerHTML = users.slice(0, 8).map(u => `
            <div class="user-mini-card" onclick="abrirUserPanel(${u.id})">
                <div class="mini-avatar">${u.nome[0]}</div>
                <div><strong>${u.nome}</strong><br><small>${u.cargo || '—'} · ${u.setor || '—'}</small></div>
            </div>
        `).join('') || '<p style="color:#546e7a;text-align:center">Nenhum usuário cadastrado.</p>';
    } catch { }
}

// ======== USUÁRIOS ========
async function carregarUsuarios() {
    const q = document.getElementById('searchUser').value;
    const status = document.getElementById('filterUserStatus').value;
    try {
        const users = await api(`/api/it/users?q=${encodeURIComponent(q)}&status=${status}`);
        const grid = document.getElementById('userGrid');
        if (!users.length) {
            grid.innerHTML = '<div class="empty-state"><div class="icon">👥</div><p>Nenhum usuário cadastrado.</p></div>';
            return;
        }
        grid.innerHTML = users.map(u => `
            <div class="user-card" onclick="abrirUserPanel(${u.id})">
                <div class="user-card-ava">${u.nome[0]}</div>
                <div class="user-card-info">
                    <div class="user-card-name">${u.nome}</div>
                    <div class="user-card-sub">${u.cargo || '—'}</div>
                    <div class="user-card-sub">${u.setor || '—'}</div>
                </div>
                <div class="user-card-right">
                    ${statusBadge(u.status)}
                    ${u.ip ? `<div style="font-size:11px;color:#7a9bc0;margin-top:4px">🌐 ${u.ip}</div>` : ''}
                    ${u.ramal ? `<div style="font-size:11px;color:#7a9bc0">📞 ${u.ramal}</div>` : ''}
                </div>
            </div>
        `).join('');
    } catch (e) { showMsg('Erro ao carregar usuários', 'error'); }
}

async function abrirUserPanel(userId) {
    currentUserId = userId;
    const panel = document.getElementById('userPanel');
    const userTab = document.getElementById('tab-usuarios');
    userTab.classList.add('hidden');
    panel.classList.remove('hidden');

    try {
        const u = await api(`/api/it/users/${userId}`);
        editingUserData = u;
        document.getElementById('panelTitle').textContent = `👤 ${u.nome} — ${u.setor || u.cargo || ''}`;

        document.getElementById('panelUserInfo').innerHTML = `
            <div class="detail-group"><div class="detail-label">Cargo</div><div class="detail-value">${u.cargo || '—'}</div></div>
            <div class="detail-group"><div class="detail-label">Setor</div><div class="detail-value">${u.setor || '—'}</div></div>
            <div class="detail-group"><div class="detail-label">E-mail Corp.</div><div class="detail-value">${u.email_corporativo || '—'}</div></div>
            <div class="detail-group"><div class="detail-label">IP</div><div class="detail-value" style="font-family:monospace">${u.ip || '—'}</div></div>
            <div class="detail-group"><div class="detail-label">Ramal</div><div class="detail-value">${u.ramal || '—'}</div></div>
            <div class="detail-group"><div class="detail-label">Cabo de Rede</div><div class="detail-value">${u.cabo_rede || '—'}</div></div>
            <div class="detail-group"><div class="detail-label">Status</div><div class="detail-value">${statusBadge(u.status)}</div></div>
            <div class="detail-group"><div class="detail-label">Entrada</div><div class="detail-value">${formatDate(u.data_entrada)}</div></div>
            <div class="detail-group"><div class="detail-label">Resp. TI</div><div class="detail-value">${u.responsavel_ti || '—'}</div></div>
        `;

        // Switch to PC sub-tab by default
        switchSubtab('pc');
    } catch (e) { showMsg('Erro ao carregar usuário', 'error'); }
}

function fecharUserPanel() {
    document.getElementById('userPanel').classList.add('hidden');
    document.getElementById('tab-usuarios').classList.remove('hidden');
    currentUserId = null;
}

// ======== USER MODAL ========
function abrirModalUser(id = null) {
    document.getElementById('formUser').reset();
    if (id) {
        document.getElementById('userId').value = id;
        document.getElementById('modalUserTitle').textContent = '✏️ Editar Usuário';
        const u = editingUserData;
        if (u) {
            document.getElementById('uNome').value = u.nome || '';
            document.getElementById('uCargo').value = u.cargo || '';
            document.getElementById('uSetor').value = u.setor || '';
            document.getElementById('uEmail').value = u.email_corporativo || '';
            document.getElementById('uRamal').value = u.ramal || '';
            document.getElementById('uCaboRede').value = u.cabo_rede || '';
            document.getElementById('uIP').value = u.ip || '';
            document.getElementById('uStatus').value = u.status || 'Ativo';
            document.getElementById('uDataEntrada').value = u.data_entrada || '';
            document.getElementById('uDataSaida').value = u.data_saida || '';
            document.getElementById('uResponsavelTI').value = u.responsavel_ti || '';
            document.getElementById('uObs').value = u.obs || '';
        }
    } else {
        document.getElementById('userId').value = '';
        document.getElementById('modalUserTitle').textContent = '👤 Novo Usuário TI';
    }
    abrirModal('modalUser');
}

function editarUsuarioAtual() { abrirModalUser(currentUserId); }

async function salvarUser(e) {
    e.preventDefault();
    const id = document.getElementById('userId').value;
    const body = {
        nome: document.getElementById('uNome').value,
        cargo: document.getElementById('uCargo').value,
        setor: document.getElementById('uSetor').value,
        email_corporativo: document.getElementById('uEmail').value,
        ramal: document.getElementById('uRamal').value,
        cabo_rede: document.getElementById('uCaboRede').value,
        ip: document.getElementById('uIP').value,
        status: document.getElementById('uStatus').value,
        data_entrada: document.getElementById('uDataEntrada').value || null,
        data_saida: document.getElementById('uDataSaida').value || null,
        responsavel_ti: document.getElementById('uResponsavelTI').value,
        obs: document.getElementById('uObs').value,
    };
    try {
        let u;
        if (id) {
            u = await api(`/api/it/users/${id}`, 'PUT', body);
            showMsg('✅ Usuário atualizado!', 'success');
        } else {
            u = await api('/api/it/users', 'POST', body);
            showMsg('✅ Usuário criado!', 'success');
        }
        fecharModal('modalUser');
        carregarUsuarios();
        if (id) abrirUserPanel(parseInt(id));
    } catch (err) { showMsg('❌ Erro: ' + err.message, 'error'); }
}

async function deletarUsuarioAtual() {
    if (!confirm('Deletar este usuário e todos os dados vinculados?')) return;
    try {
        await api(`/api/it/users/${currentUserId}`, 'DELETE');
        showMsg('🗑️ Usuário removido', 'info');
        fecharUserPanel();
        carregarUsuarios();
    } catch (err) { showMsg('❌ Erro: ' + err.message, 'error'); }
}

// ======== PC PANEL ========
async function carregarPanelPC() {
    if (!currentUserId) return;
    try {
        const pc = await api(`/api/it/users/${currentUserId}/pc`);
        const div = document.getElementById('panelPC');
        if (!pc) {
            div.innerHTML = '<div class="empty-state"><div class="icon">🖥️</div><p>Nenhum PC cadastrado. Clique em "Editar PC" para adicionar.</p></div>';
            return;
        }
        div.innerHTML = `
            <div class="pc-detail-grid">
                <div class="detail-group"><div class="detail-label">Hostname</div><div class="detail-value" style="font-family:monospace">${pc.hostname || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Nº Série</div><div class="detail-value">${pc.num_serie || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Nº Patrimônio</div><div class="detail-value">${pc.num_patrimonio || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Fabricante/Modelo</div><div class="detail-value">${pc.fabricante || ''} ${pc.modelo || ''}</div></div>
                <div class="detail-group"><div class="detail-label">Status</div><div class="detail-value">${statusBadge(pc.status)}</div></div>
                <div class="detail-group"><div class="detail-label">Compra</div><div class="detail-value">${formatDate(pc.data_compra)}</div></div>
                <div class="detail-group"><div class="detail-label">Garantia até</div><div class="detail-value">${formatDate(pc.data_garantia_fim)}</div></div>
                <div class="detail-group"><div class="detail-label">Processador</div><div class="detail-value">${pc.processador || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">RAM</div><div class="detail-value">${pc.ram || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Placa Mãe</div><div class="detail-value">${pc.placa_mae || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Placa Vídeo</div><div class="detail-value">${pc.placa_video || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Monitor</div><div class="detail-value">${pc.monitor || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Teclado</div><div class="detail-value">${pc.teclado || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Mouse</div><div class="detail-value">${pc.mouse || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Gabinete</div><div class="detail-value">${pc.gabinete || '—'}</div></div>
                <div class="detail-group"><div class="detail-label">Fonte</div><div class="detail-value">${pc.fonte || '—'}</div></div>
            </div>
            ${pc.hdds ? `<div class="detail-group" style="margin-top:10px"><div class="detail-label">💿 Armazenamento</div><div class="detail-value">${pc.hdds}</div></div>` : ''}
            ${pc.obs ? `<div class="detail-group" style="margin-top:6px"><div class="detail-label">📝 Obs.</div><div class="detail-value">${pc.obs}</div></div>` : ''}
            ${pc.manutencoes && pc.manutencoes.length ? `
                <h4 style="margin-top:18px;color:#90caf9;font-size:14px">🔧 Manutenções</h4>
                <div class="table-responsive" style="margin-top:8px">
                    <table class="it-table">
                        <thead><tr><th>Data</th><th>Tipo</th><th>Descrição</th><th>Técnico</th><th>Status</th><th>Custo</th><th>Ação</th></tr></thead>
                        <tbody>${pc.manutencoes.map(m => `
                            <tr>
                                <td>${formatDate(m.data)}</td>
                                <td>${m.tipo}</td>
                                <td>${m.descricao || '—'}</td>
                                <td>${m.tecnico || '—'}</td>
                                <td>${statusBadge(m.status)}</td>
                                <td>${m.custo ? 'R$ ' + m.custo : '—'}</td>
                                <td><button class="btn-danger btn-sm" onclick="deletarManutencao(${m.id})">🗑️</button></td>
                            </tr>`).join('')}
                        </tbody>
                    </table>
                </div>
            ` : ''}
            <div style="margin-top:12px">
                <button class="btn-glow" onclick="abrirModalManutencao(${pc.id})">➕ Registrar Manutenção</button>
            </div>
        `;
    } catch (e) { showMsg('Erro ao carregar PC', 'error'); }
}

function abrirModalPC(userId) {
    document.getElementById('pcUserId').value = userId;
    // load existing data
    api(`/api/it/users/${userId}/pc`).then(pc => {
        if (pc) {
            ['Hostname', 'NumSerie', 'NumPatrimonio', 'Fabricante', 'Modelo', 'Status', 'Monitor',
                'MousePad', 'Mouse', 'Teclado', 'Gabinete', 'Processador', 'Ram', 'PlacaMae',
                'PlacaVideo', 'PlacaRede', 'Fonte', 'Hdds', 'Obs'].forEach(f => {
                    const el = document.getElementById('pc' + f);
                    const key = f.charAt(0).toLowerCase() + f.slice(1).replace(/([A-Z])/g, '_$1').toLowerCase().replace('_', '_');
                    const snakeKey = f.replace(/([A-Z])/g, c => '_' + c.toLowerCase()).replace(/^_/, '');
                    if (el) el.value = pc[snakeKey] || '';
                });
            if (pc.data_compra) document.getElementById('pcDataCompra').value = pc.data_compra;
            if (pc.data_garantia_fim) document.getElementById('pcDataGarantiafim').value = pc.data_garantia_fim;
            document.getElementById('pcStatus').value = pc.status || 'Em Uso';
        }
    }).catch(() => { });
    abrirModal('modalPC');
}

async function salvarPC(e) {
    e.preventDefault();
    const userId = document.getElementById('pcUserId').value;
    const body = {
        hostname: document.getElementById('pcHostname').value,
        num_serie: document.getElementById('pcNumSerie').value,
        num_patrimonio: document.getElementById('pcNumPatrimonio').value,
        fabricante: document.getElementById('pcFabricante').value,
        modelo: document.getElementById('pcModelo').value,
        data_compra: document.getElementById('pcDataCompra').value || null,
        data_garantia_fim: document.getElementById('pcDataGarantiafim').value || null,
        status: document.getElementById('pcStatus').value,
        monitor: document.getElementById('pcMonitor').value,
        mouse_pad: document.getElementById('pcMousePad').value,
        mouse: document.getElementById('pcMouse').value,
        teclado: document.getElementById('pcTeclado').value,
        gabinete: document.getElementById('pcGabinete').value,
        processador: document.getElementById('pcProcessador').value,
        ram: document.getElementById('pcRam').value,
        placa_mae: document.getElementById('pcPlacaMae').value,
        placa_video: document.getElementById('pcPlacaVideo').value,
        placa_rede: document.getElementById('pcPlacaRede').value,
        fonte: document.getElementById('pcFonte').value,
        hdds: document.getElementById('pcHdds').value,
        obs: document.getElementById('pcObs').value,
    };
    try {
        await api(`/api/it/users/${userId}/pc`, 'PUT', body);
        showMsg('✅ PC salvo!', 'success');
        fecharModal('modalPC');
        carregarPanelPC();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

// Manutenção modal (inline creation)
let currentPCId = null;
function abrirModalManutencao(pcId) {
    currentPCId = pcId;
    const data = prompt('Data (AAAA-MM-DD):');
    const tipo = prompt('Tipo (Preventiva/Corretiva):') || 'Corretiva';
    const descricao = prompt('Descrição:');
    const tecnico = prompt('Técnico responsável:');
    const custo = prompt('Custo (R$):');
    if (!descricao) return;
    api(`/api/it/pcs/${pcId}/manutencoes`, 'POST', {
        data, tipo, descricao, tecnico, custo, status: 'Concluída'
    }).then(() => { showMsg('✅ Manutenção registrada!', 'success'); carregarPanelPC(); })
        .catch(e => showMsg('❌ ' + e.message, 'error'));
}

async function deletarManutencao(id) {
    if (!confirm('Deletar registro de manutenção?')) return;
    await api(`/api/it/manutencoes/${id}`, 'DELETE');
    showMsg('🗑️ Removido', 'info');
    carregarPanelPC();
}

// ======== CONTAS ========
let editingContaId = null;

function toggleCustomSistema() {
    document.getElementById('customSistemaGroup').style.display =
        document.getElementById('cSistema').value === 'Outro' ? 'block' : 'none';
}

function abrirModalConta(dados = null) {
    editingContaId = null;
    document.getElementById('formConta').reset();
    document.getElementById('customSistemaGroup').style.display = 'none';
    document.getElementById('modalContaTitle').textContent = '🔐 Nova Conta';
    if (dados) {
        editingContaId = dados.id;
        document.getElementById('modalContaTitle').textContent = '✏️ Editar Conta';
        document.getElementById('contaId').value = dados.id;
        document.getElementById('cSistema').value = dados.sistema;
        document.getElementById('cNomeCustom').value = dados.nome_custom || '';
        document.getElementById('cLogin').value = dados.login || '';
        document.getElementById('cSenha').value = dados.senha || '';
        document.getElementById('cAcessos').value = dados.acessos || '';
        document.getElementById('cRevisao').value = dados.data_ultima_revisao || '';
        document.getElementById('cObs').value = dados.obs || '';
        if (dados.sistema === 'Outro') document.getElementById('customSistemaGroup').style.display = 'block';
    }
    abrirModal('modalConta');
}

async function carregarPanelContas() {
    if (!currentUserId) return;
    const contas = await api(`/api/it/users/${currentUserId}/contas`).catch(() => []);
    const div = document.getElementById('panelContas');
    if (!contas.length) { div.innerHTML = '<div class="empty-state"><div class="icon">🔐</div><p>Nenhuma conta cadastrada.</p></div>'; return; }
    div.innerHTML = `<div class="table-responsive"><table class="it-table">
        <thead><tr><th>Sistema</th><th>Login</th><th>Senha</th><th>Acessos</th><th>Última Revisão</th><th>Status</th><th>Ações</th></tr></thead>
        <tbody>${contas.map(c => `
            <tr>
                <td><strong>${c.nome_custom || c.sistema}</strong></td>
                <td><span style="font-family:monospace">${c.login || '—'}</span>${c.login ? ` <button class="btn-sm" onclick="navigator.clipboard.writeText('${c.login}');showMsg('✅ Login copiado','success')">📋</button>` : ''}</td>
                <td>${c.senha ? `<span class="pwd-blur" onclick="this.classList.toggle('pwd-show')">••••••</span> <button class="btn-sm" onclick="navigator.clipboard.writeText('${c.senha}');showMsg('✅ Senha copiada','success')">📋</button>` : '—'}</td>
                <td style="max-width:200px;font-size:11px">${(c.acessos || '—').slice(0, 80)}</td>
                <td>${formatDate(c.data_ultima_revisao)}</td>
                <td>${revisaoStatus(c.data_ultima_revisao)}</td>
                <td>
                    <button class="btn-card btn-card-edit" onclick="abrirModalConta(${JSON.stringify(c).replace(/"/g, '&quot;')})">✏️</button>
                    <button class="btn-danger btn-sm" onclick="deletarConta(${c.id})">🗑️</button>
                </td>
            </tr>`).join('')}
        </tbody></table></div>`;
}

async function salvarConta(e) {
    e.preventDefault();
    const id = editingContaId;
    const body = {
        sistema: document.getElementById('cSistema').value,
        nome_custom: document.getElementById('cNomeCustom').value,
        login: document.getElementById('cLogin').value,
        senha: document.getElementById('cSenha').value,
        acessos: document.getElementById('cAcessos').value,
        data_ultima_revisao: document.getElementById('cRevisao').value || null,
        obs: document.getElementById('cObs').value,
    };
    try {
        if (id) { await api(`/api/it/contas/${id}`, 'PUT', body); }
        else { await api(`/api/it/users/${currentUserId}/contas`, 'POST', body); }
        showMsg('✅ Conta salva!', 'success');
        fecharModal('modalConta');
        carregarPanelContas();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

async function deletarConta(id) {
    if (!confirm('Deletar?')) return;
    await api(`/api/it/contas/${id}`, 'DELETE');
    showMsg('🗑️ Removido', 'info');
    carregarPanelContas();
}

// ======== EMAILS ========
let editingEmailId = null;

function abrirModalEmail(dados = null) {
    editingEmailId = null;
    document.getElementById('formEmail').reset();
    document.getElementById('modalEmailTitle').textContent = '📧 Novo E-mail';
    if (dados) {
        editingEmailId = dados.id;
        document.getElementById('modalEmailTitle').textContent = '✏️ Editar E-mail';
        document.getElementById('emailId').value = dados.id;
        document.getElementById('eEndereco').value = dados.endereco || '';
        document.getElementById('eServidor').value = dados.servidor || '';
        document.getElementById('eLogin').value = dados.login || '';
        document.getElementById('eSenha').value = dados.senha || '';
        document.getElementById('eObs').value = dados.obs || '';
    }
    abrirModal('modalEmail');
}

async function carregarPanelEmails() {
    if (!currentUserId) return;
    // Carrega vínculos do modelo global
    const vinculos = await api(`/api/it/users/${currentUserId}/email-vinculos`).catch(() => []);
    const div = document.getElementById('panelEmails');
    if (!vinculos.length) {
        div.innerHTML = '<div class="empty-state"><div class="icon">📧</div><p>Nenhum e-mail vinculado a este usuário. Vincule-o na aba "📧 E-mails" do menu principal.</p></div>';
        return;
    }
    div.innerHTML = `<div class="table-responsive"><table class="it-table">
        <thead><tr><th>E-mail</th><th>Servidor</th><th>Login</th><th>PC</th><th>Ações</th></tr></thead>
        <tbody>${vinculos.map(v => `
            <tr>
                <td><strong>${v.endereco}</strong></td>
                <td>${v.servidor || '—'}</td>
                <td>${v.login || '—'}</td>
                <td><small style="font-family:monospace">${v.hostname_pc || '—'}</small></td>
                <td>
                    <button class="btn-danger btn-sm" onclick="deletarEmailVinculo(${v.id})">🗑️</button>
                </td>
            </tr>`).join('')}
        </tbody></table></div>`;
}

async function deletarEmailVinculo(id) {
    if (!confirm('Remover vínculo deste e-mail com o usuário?')) return;
    try {
        await api(`/api/it/email-vinculos/${id}`, 'DELETE');
        showMsg('🗑️ Vínculo removido', 'info');
        carregarPanelEmails();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

// ======== NAS USER PANEL ========
async function carregarPanelNAS() {
    if (!currentUserId) return;
    const acessos = await api(`/api/it/users/${currentUserId}/nas-acessos`).catch(() => []);
    const div = document.getElementById('panelNAS');
    if (!acessos.length) {
        div.innerHTML = '<div class="empty-state"><div class="icon">💾</div><p>Sem pastas NAS vinculadas. Vincule na aba "💾 NAS" do menu principal.</p></div>';
        return;
    }
    div.innerHTML = `<div class="table-responsive"><table class="it-table">
        <thead><tr><th>Pasta</th><th>Mapeamento</th><th>Caminho</th><th>Permissão</th><th>Ações</th></tr></thead>
        <tbody>${acessos.map(a => `
            <tr>
                <td><strong>${a.pasta_nome}</strong></td>
                <td><span class="badge-info">${a.letra_mapeada || '—'}</span></td>
                <td><small style="font-family:monospace">${a.caminho_rede || '—'}</small></td>
                <td>${a.permissao}</td>
                <td>
                    <button class="btn-danger btn-sm" onclick="deletarNASAcesso(${a.id})">🗑️</button>
                </td>
            </tr>`).join('')}
        </tbody></table></div>`;
}

async function deletarNASAcesso(id) {
    if (!confirm('Remover acesso deste usuário a esta pasta?')) return;
    try {
        await api(`/api/it/nas-acessos/${id}`, 'DELETE');
        showMsg('🗑️ Acesso removido', 'info');
        carregarPanelNAS();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

// ======== CERTIFICADOS ========
let editingCertId = null;

function toggleCertOutro() {
    document.getElementById('certOutroGroup').style.display =
        document.getElementById('certTipo').value === 'Outro' ? 'block' : 'none';
}

function abrirModalCertificado(dados = null) {
    editingCertId = null;
    document.getElementById('formCertificado').reset();
    document.getElementById('certOutroGroup').style.display = 'none';
    document.getElementById('modalCertTitle').textContent = '🔑 Novo Certificado';
    if (dados) {
        editingCertId = dados.id;
        document.getElementById('modalCertTitle').textContent = '✏️ Editar';
        document.getElementById('certId').value = dados.id;
        document.getElementById('certTipo').value = dados.tipo;
        document.getElementById('certNomeOutro').value = dados.nome_outro || '';
        document.getElementById('certVersao').value = dados.versao || '';
        document.getElementById('certChave').value = dados.chave || '';
        document.getElementById('certValidade').value = dados.validade || '';
        document.getElementById('certFornecedor').value = dados.fornecedor || '';
        document.getElementById('certObs').value = dados.obs || '';
        if (dados.tipo === 'Outro') document.getElementById('certOutroGroup').style.display = 'block';
    }
    abrirModal('modalCertificado');
}

async function carregarPanelCerts() {
    if (!currentUserId) return;
    const certs = await api(`/api/it/users/${currentUserId}/certificados`).catch(() => []);
    const div = document.getElementById('panelCerts');
    if (!certs.length) { div.innerHTML = '<div class="empty-state"><div class="icon">🔑</div><p>Nenhum certificado.</p></div>'; return; }
    div.innerHTML = `<div class="table-responsive"><table class="it-table">
        <thead><tr><th>Tipo</th><th>Versão</th><th>Validade</th><th>Status</th><th>Fornecedor</th><th>Ações</th></tr></thead>
        <tbody>${certs.map(c => `
            <tr>
                <td><strong>${c.nome_outro || c.tipo}</strong></td>
                <td>${c.versao || '—'}</td>
                <td>${formatDate(c.validade)}</td>
                <td>${certStatus(c.validade)}</td>
                <td>${c.fornecedor || '—'}</td>
                <td>
                    ${c.chave ? `<button class="btn-sm" onclick="navigator.clipboard.writeText('${c.chave}');showMsg('✅ Chave copiada','success')">🔑 Copiar</button>` : ''}
                    <button class="btn-card btn-card-edit" onclick="abrirModalCertificado(${JSON.stringify(c).replace(/"/g, '&quot;')})">✏️</button>
                    <button class="btn-danger btn-sm" onclick="deletarCert(${c.id})">🗑️</button>
                </td>
            </tr>`).join('')}
        </tbody></table></div>`;
}

async function salvarCertificado(e) {
    e.preventDefault();
    const id = editingCertId;
    const body = {
        tipo: document.getElementById('certTipo').value,
        nome_outro: document.getElementById('certNomeOutro').value,
        versao: document.getElementById('certVersao').value,
        chave: document.getElementById('certChave').value,
        validade: document.getElementById('certValidade').value || null,
        fornecedor: document.getElementById('certFornecedor').value,
        obs: document.getElementById('certObs').value,
    };
    try {
        if (id) { await api(`/api/it/certificados/${id}`, 'PUT', body); }
        else { await api(`/api/it/users/${currentUserId}/certificados`, 'POST', body); }
        showMsg('✅ Salvo!', 'success');
        fecharModal('modalCertificado');
        carregarPanelCerts();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

async function deletarCert(id) {
    if (!confirm('Deletar?')) return;
    await api(`/api/it/certificados/${id}`, 'DELETE');
    showMsg('🗑️', 'info');
    carregarPanelCerts();
}

// ======== PROGRAMAS ========
let editingProgId = null;

function abrirModalPrograma(dados = null) {
    editingProgId = null;
    document.getElementById('formPrograma').reset();
    document.getElementById('modalProgTitle').textContent = '📦 Novo Programa';
    if (dados) {
        editingProgId = dados.id;
        document.getElementById('modalProgTitle').textContent = '✏️ Editar';
        document.getElementById('progId').value = dados.id;
        document.getElementById('pNome').value = dados.nome || '';
        document.getElementById('pVersao').value = dados.versao || '';
        document.getElementById('pChave').value = dados.chave || '';
        document.getElementById('pCategoria').value = dados.categoria || 'Outro';
        document.getElementById('pObs').value = dados.obs || '';
    }
    abrirModal('modalPrograma');
}

async function carregarPanelProgs() {
    if (!currentUserId) return;
    const progs = await api(`/api/it/users/${currentUserId}/programas`).catch(() => []);
    const div = document.getElementById('panelProgs');
    if (!progs.length) { div.innerHTML = '<div class="empty-state"><div class="icon">📦</div><p>Nenhum programa.</p></div>'; return; }
    div.innerHTML = `<div class="table-responsive"><table class="it-table">
        <thead><tr><th>Programa</th><th>Versão</th><th>Categoria</th><th>Ações</th></tr></thead>
        <tbody>${progs.map(p => `
            <tr>
                <td><strong>${p.nome}</strong></td>
                <td>${p.versao || '—'}</td>
                <td>${p.categoria || '—'}</td>
                <td>
                    ${p.chave ? `<button class="btn-sm" onclick="navigator.clipboard.writeText('${p.chave}');showMsg('✅ Chave copiada','success')">🔑 Copiar</button>` : ''}
                    <button class="btn-card btn-card-edit" onclick="abrirModalPrograma(${JSON.stringify(p).replace(/"/g, '&quot;')})">✏️</button>
                    <button class="btn-danger btn-sm" onclick="deletarProg(${p.id})">🗑️</button>
                </td>
            </tr>`).join('')}
        </tbody></table></div>`;
}

async function salvarPrograma(e) {
    e.preventDefault();
    const id = editingProgId;
    const body = {
        nome: document.getElementById('pNome').value,
        versao: document.getElementById('pVersao').value,
        chave: document.getElementById('pChave').value,
        categoria: document.getElementById('pCategoria').value,
        obs: document.getElementById('pObs').value,
    };
    try {
        if (id) { await api(`/api/it/programas/${id}`, 'PUT', body); }
        else { await api(`/api/it/users/${currentUserId}/programas`, 'POST', body); }
        showMsg('✅ Salvo!', 'success');
        fecharModal('modalPrograma');
        carregarPanelProgs();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

async function deletarProg(id) {
    if (!confirm('Deletar?')) return;
    await api(`/api/it/programas/${id}`, 'DELETE');
    showMsg('🗑️', 'info');
    carregarPanelProgs();
}

// ======== GLOBAL VIEWS ========
async function carregarAtivos() {
    const q = document.getElementById('searchAtivo').value.toLowerCase();
    const pcs = await api('/api/it/pcs').catch(() => []);
    const body = document.getElementById('ativosBody');
    const filtered = pcs.filter(p =>
        [p.hostname, p.num_serie, p.num_patrimonio, p.usuario_nome].join(' ').toLowerCase().includes(q)
    );
    if (!filtered.length) { body.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#546e7a">Nenhum ativo encontrado.</td></tr>'; return; }
    body.innerHTML = filtered.map(p => `
        <tr>
            <td><strong style="font-family:monospace">${p.hostname || '—'}</strong></td>
            <td>${p.usuario_nome}</td>
            <td>${p.num_patrimonio || '—'}</td>
            <td>${p.num_serie || '—'}</td>
            <td>${p.processador || '—'}</td>
            <td>${p.ram || '—'}</td>
            <td>${statusBadge(p.status)}</td>
            <td>${formatDate(p.data_garantia_fim)}</td>
            <td>${p.it_user_id ? `<button class="btn-card btn-card-view" onclick="abrirUserPanel(${p.it_user_id});switchTab('usuarios')">Ver</button>` : ''}</td>
        </tr>`).join('');
}

async function carregarCertificadosGlobal() {
    const certs = await api('/api/it/users').then(async users => {
        const all = [];
        for (const u of users) {
            const uc = await api(`/api/it/users/${u.id}/certificados`).catch(() => []);
            uc.forEach(c => { c._userName = u.nome; all.push(c); });
        }
        return all;
    }).catch(() => []);
    document.getElementById('certsBody').innerHTML = certs.map(c => `
        <tr>
            <td><strong>${c.nome_outro || c.tipo}</strong></td>
            <td>${c.versao || '—'}</td>
            <td>${c._userName}</td>
            <td>${formatDate(c.validade)}</td>
            <td>${certStatus(c.validade)}</td>
            <td>${c.fornecedor || '—'}</td>
            <td>${c.chave ? `<button class="btn-sm" onclick="navigator.clipboard.writeText('${c.chave}');showMsg('✅ Copiado','success')">📋</button>` : '—'}</td>
        </tr>`).join('') || '<tr><td colspan="7" style="text-align:center;color:#546e7a">Nenhum certificado.</td></tr>';
}

// ======== EMAIL GLOBAL ========
let editingEmailGlobalId = null;
let emailVinculoEmailIdCurrent = null;

async function carregarEmailsGlobal() {
    const q = (document.getElementById('searchEmailGlobal') || {}).value || '';
    const emails = await api(`/api/it/emails-global?q=${encodeURIComponent(q)}`).catch(() => []);
    const grid = document.getElementById('emailGlobalGrid');
    if (!emails.length) { grid.innerHTML = '<div class="empty-state"><div class="icon">📧</div><p>Nenhum e-mail cadastrado. Clique em "➕ Novo E-mail" para começar.</p></div>'; return; }
    grid.innerHTML = emails.map(em => {
        const vincCount = (em.vinculos || []).length;
        return `
        <div class="email-global-card">
            <div class="email-card-header">
                <div>
                    <div class="email-card-address">📧 ${em.endereco}</div>
                    <div class="email-card-meta">${em.tipo} · ${em.servidor || '—'}</div>
                </div>
                <div style="display:flex;gap:6px;flex-shrink:0">
                    <button class="btn-card btn-card-edit" onclick="editarEmailGlobal(${em.id})">✏️</button>
                    <button class="btn-danger btn-sm" onclick="deletarEmailGlobal(${em.id})">🗑️</button>
                </div>
            </div>
            <div class="email-card-credentials">
                ${em.login ? `<div><span class="em-label">Login:</span> <span style="font-family:monospace">${em.login}</span> <button class="btn-sm" onclick="navigator.clipboard.writeText('${em.login}');showMsg('✅ Copiado','success')">📋</button></div>` : ''}
                ${em.senha ? `<div><span class="em-label">Senha:</span> <span class="pwd-blur" onclick="this.classList.toggle('pwd-show')">••••••</span> <button class="btn-sm" onclick="navigator.clipboard.writeText('${em.senha}');showMsg('✅ Copiado','success')">📋</button></div>` : ''}
            </div>
            <div class="email-card-users">
                <div class="email-users-header">
                    <span>👤 Vinculado a ${vincCount} usuário(s)</span>
                    <button class="btn-sm btn-glow" onclick="abrirModalEmailVinculo(${em.id},'${em.endereco}')">➕ Vincular Usuário</button>
                </div>
                ${(em.vinculos || []).map(v => `
                    <div class="email-vinculo-item">
                        <div class="mini-avatar mini-avatar-sm">${v.user_nome ? v.user_nome[0] : '?'}</div>
                        <div>
                            <strong>${v.user_nome || '?'}</strong>
                            ${v.hostname_pc ? `<span style="color:#7a9bc0;font-size:11px"> · ${v.hostname_pc}</span>` : ''}
                            ${v.cliente_email ? `<span style="color:#7a9bc0;font-size:11px"> · ${v.cliente_email}</span>` : ''}
                        </div>
                        <button class="btn-danger btn-sm" onclick="removerEmailVinculo(${v.id})">✕</button>
                    </div>`).join('') || '<div style="color:#546e7a;font-size:12px;margin-top:6px">Nenhum usuário vinculado ainda.</div>'}
            </div>
        </div>
        `;
    }).join('');
}

function abrirModalEmailGlobal(dados = null) {
    editingEmailGlobalId = null;
    document.getElementById('formEmailGlobal').reset();
    document.getElementById('modalEmailGlobalTitle').textContent = '📧 Novo E-mail';
    if (dados) {
        editingEmailGlobalId = dados.id;
        document.getElementById('modalEmailGlobalTitle').textContent = '✏️ Editar E-mail';
        document.getElementById('emailGlobalId').value = dados.id;
        document.getElementById('egEndereco').value = dados.endereco || '';
        document.getElementById('egTipo').value = dados.tipo || 'Corporativo';
        document.getElementById('egServidor').value = dados.servidor || '';
        document.getElementById('egLogin').value = dados.login || '';
        document.getElementById('egSenha').value = dados.senha || '';
        document.getElementById('egObs').value = dados.obs || '';
    }
    abrirModal('modalEmailGlobal');
}

async function editarEmailGlobal(id) {
    try {
        const em = await api(`/api/it/emails-global/${id}`);
        abrirModalEmailGlobal(em);
    } catch (e) { showMsg('❌ Erro ao carregar e-mail', 'error'); }
}

async function salvarEmailGlobal(e) {
    e.preventDefault();
    const id = editingEmailGlobalId;
    const body = {
        endereco: document.getElementById('egEndereco').value,
        tipo: document.getElementById('egTipo').value,
        servidor: document.getElementById('egServidor').value,
        login: document.getElementById('egLogin').value,
        senha: document.getElementById('egSenha').value,
        obs: document.getElementById('egObs').value,
    };
    try {
        if (id) { await api(`/api/it/emails-global/${id}`, 'PUT', body); }
        else { await api('/api/it/emails-global', 'POST', body); }
        showMsg('✅ E-mail salvo!', 'success');
        fecharModal('modalEmailGlobal');
        carregarEmailsGlobal();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

async function deletarEmailGlobal(id) {
    if (!confirm('Deletar este e-mail e todos os vínculos com usuários?')) return;
    await api(`/api/it/emails-global/${id}`, 'DELETE');
    showMsg('🗑️ E-mail removido', 'info');
    carregarEmailsGlobal();
}

async function abrirModalEmailVinculo(emailId, emailEndereco) {
    emailVinculoEmailIdCurrent = emailId;
    document.getElementById('formEmailVinculo').reset();
    document.getElementById('emailVinculoEmailId').value = emailId;
    document.getElementById('emailVinculoEmailDisplay').textContent = `📧 ${emailEndereco}`;
    // Fill user select
    const users = await api('/api/it/users?status=Ativo').catch(() => []);
    const sel = document.getElementById('evUserId');
    sel.innerHTML = '<option value="">— Selecione o usuário —</option>' +
        users.map(u => `<option value="${u.id}">${u.nome} (${u.setor || u.cargo || ''})</option>`).join('');
    abrirModal('modalEmailVinculo');
}

async function salvarEmailVinculo(e) {
    e.preventDefault();
    const emailId = document.getElementById('emailVinculoEmailId').value;
    const body = {
        it_user_id: parseInt(document.getElementById('evUserId').value),
        hostname_pc: document.getElementById('evHostname').value,
        cliente_email: document.getElementById('evClienteEmail').value,
        obs: document.getElementById('evObs').value,
    };
    try {
        await api(`/api/it/emails-global/${emailId}/vinculos`, 'POST', body);
        showMsg('✅ Usuário vinculado!', 'success');
        fecharModal('modalEmailVinculo');
        carregarEmailsGlobal();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

async function removerEmailVinculo(vinculoId) {
    if (!confirm('Remover vínculo deste e-mail com o usuário?')) return;
    await api(`/api/it/email-vinculos/${vinculoId}`, 'DELETE');
    showMsg('✅ Vínculo removido', 'info');
    carregarEmailsGlobal();
}

async function carregarProgramasGlobal() {
    const users = await api('/api/it/users').catch(() => []);
    let all = [];
    for (const u of users) {
        const progs = await api(`/api/it/users/${u.id}/programas`).catch(() => []);
        progs.forEach(p => { p._userName = u.nome; all.push(p); });
    }
    document.getElementById('programasBody').innerHTML = all.map(p => `
        <tr>
            <td><strong>${p.nome}</strong></td>
            <td>${p.versao || '—'}</td>
            <td>${p.categoria || '—'}</td>
            <td>${p._userName}</td>
            <td>${p.chave ? `<button class="btn-sm" onclick="navigator.clipboard.writeText('${p.chave}');showMsg('✅ Chave copiada','success')">🔑</button>` : '—'}</td>
        </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:#546e7a">Nenhum programa.</td></tr>';
}

async function carregarContasGlobal() {
    const users = await api('/api/it/users').catch(() => []);
    let all = [];
    for (const u of users) {
        const contas = await api(`/api/it/users/${u.id}/contas`).catch(() => []);
        contas.forEach(c => { c._userName = u.nome; c._userId = u.id; all.push(c); });
    }
    document.getElementById('contasBody').innerHTML = all.map(c => `
        <tr>
            <td><strong>${c.nome_custom || c.sistema}</strong></td>
            <td>${c._userName}</td>
            <td>${c.login || '—'}</td>
            <td>${formatDate(c.data_ultima_revisao)}</td>
            <td>${revisaoStatus(c.data_ultima_revisao)}</td>
            <td>
                <button class="btn-sm" onclick="alert('Revisado em ${new Date().toLocaleDateString('pt-BR')}');api('/api/it/contas/${c.id}','PUT',{data_ultima_revisao:'${new Date().toISOString().split('T')[0]}'}).then(()=>{showMsg('✅ Revisão marcada','success');carregarContasGlobal()})">✅ Marcar Revisão</button>
            </td>
        </tr>`).join('') || '<tr><td colspan="6" style="text-align:center;color:#546e7a">Nenhuma conta.</td></tr>';
}

// ======== AUDITORIA ========
async function carregarAuditoria() {
    const tabela = document.getElementById('filterAuditTabela').value;
    const logs = await api(`/api/it/audit?tabela=${tabela}&limit=200`).catch(() => []);
    document.getElementById('auditBody').innerHTML = logs.map(l => `
        <tr>
            <td style="font-size:11px;font-family:monospace">${l.timestamp ? new Date(l.timestamp).toLocaleString('pt-BR') : '—'}</td>
            <td>${l.usuario_sistema}</td>
            <td>${l.acao === 'CREATE' ? '🟢 Criacao' : l.acao === 'UPDATE' ? '🟡 Alteração' : '🔴 Exclusão'}</td>
            <td><code>${l.tabela}</code></td>
            <td>${l.campo || '—'}</td>
            <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;font-size:11px">${l.valor_anterior || '—'}</td>
            <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;font-size:11px">${l.valor_novo || '—'}</td>
        </tr>`).join('') || '<tr><td colspan="7" style="text-align:center;color:#546e7a">Nenhum log.</td></tr>';
}

// ======== STICKY NOTES ========
function selectColor(c) {
    stickyColor = c;
    document.querySelectorAll('#modalSticky .color-dot').forEach(d => {
        d.classList.toggle('selected', d.dataset.color === c);
    });
}

let editingStickyId = null;

function novaStickyNote() {
    editingStickyId = null;
    document.getElementById('formSticky').reset();
    document.getElementById('modalStickyTitle').textContent = '📝 Nova Nota';
    stickyColor = 'yellow';
    document.querySelectorAll('#modalSticky .color-dot').forEach(d => d.classList.remove('selected'));
    document.querySelector('[data-color="yellow"]').classList.add('selected');
    abrirModal('modalSticky');
}

async function carregarSticky() {
    const q = document.getElementById('searchSticky').value.toLowerCase();
    const notes = await api('/api/it/sticky').catch(() => []);
    const filtered = notes.filter(n =>
        [n.titulo, n.conteudo, ...(n.tags || [])].join(' ').toLowerCase().includes(q)
    );

    const allTags = [...new Set(notes.flatMap(n => n.tags || []))];
    document.getElementById('tagFilters').innerHTML =
        allTags.map(t => `<button class="tag-filter-btn" onclick="filtrarStickyTag('${t}')">#${t}</button>`).join('');

    document.getElementById('stickyGrid').innerHTML = filtered.map(n => `
        <div class="sticky-note sticky-${n.color || 'yellow'}">
            <div class="sticky-header">
                <div class="sticky-title">${n.titulo || 'Sem título'}</div>
                <div class="sticky-actions-top">
                    <button class="sticky-btn" onclick="editarSticky(${n.id})">✏️</button>
                    <button class="sticky-btn" onclick="deletarSticky(${n.id})">🗑️</button>
                </div>
            </div>
            <div class="sticky-content">${n.conteudo}</div>
            <div class="sticky-tags">${(n.tags || []).map(t => `<span class="sticky-tag">#${t}</span>`).join('')}</div>
        </div>`).join('') || '<div class="empty-state"><div class="icon">📝</div><p>Nenhuma nota.</p></div>';
}

async function filtrarStickyTag(tag) {
    const notes = await api(`/api/it/sticky?tag=${encodeURIComponent(tag)}`).catch(() => []);
    document.getElementById('stickyGrid').innerHTML = notes.map(n => `
        <div class="sticky-note sticky-${n.color || 'yellow'}">
            <div class="sticky-header"><div class="sticky-title">${n.titulo || 'Sem título'}</div>
                <div class="sticky-actions-top">
                    <button class="sticky-btn" onclick="editarSticky(${n.id})">✏️</button>
                    <button class="sticky-btn" onclick="deletarSticky(${n.id})">🗑️</button>
                </div></div>
            <div class="sticky-content">${n.conteudo}</div>
            <div class="sticky-tags">${(n.tags || []).map(t => `<span class="sticky-tag">#${t}</span>`).join('')}</div>
        </div>`).join('');
}

async function editarSticky(id) {
    const notes = await api('/api/it/sticky').catch(() => []);
    const n = notes.find(x => x.id === id);
    if (!n) return;
    editingStickyId = id;
    document.getElementById('stickyId').value = id;
    document.getElementById('sTitulo').value = n.titulo || '';
    document.getElementById('sConteudo').value = n.conteudo || '';
    document.getElementById('sTags').value = (n.tags || []).join(', ');
    stickyColor = n.color || 'yellow';
    document.querySelectorAll('#modalSticky .color-dot').forEach(d =>
        d.classList.toggle('selected', d.dataset.color === stickyColor)
    );
    document.getElementById('modalStickyTitle').textContent = '✏️ Editar Nota';
    abrirModal('modalSticky');
}

async function salvarSticky(e) {
    e.preventDefault();
    const id = editingStickyId;
    const body = {
        titulo: document.getElementById('sTitulo').value,
        conteudo: document.getElementById('sConteudo').value,
        tags: document.getElementById('sTags').value.split(',').map(t => t.trim()).filter(Boolean),
        color: stickyColor,
    };
    try {
        if (id) { await api(`/api/it/sticky/${id}`, 'PUT', body); }
        else { await api('/api/it/sticky', 'POST', body); }
        showMsg('✅ Nota salva!', 'success');
        fecharModal('modalSticky');
        carregarSticky();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

async function deletarSticky(id) {
    if (!confirm('Deletar nota?')) return;
    await api(`/api/it/sticky/${id}`, 'DELETE');
    showMsg('🗑️', 'info');
    carregarSticky();
}

// ======== NAS PASTAS ========
let editingNASPastaId = null;
let nasAcessoPastaIdCurrent = null;

async function carregarNASPastas() {
    const q = (document.getElementById('searchNAS') || {}).value || '';
    const pastas = await api(`/api/it/nas-pastas?q=${encodeURIComponent(q)}`).catch(() => []);
    const grid = document.getElementById('nasGrid');
    if (!pastas.length) {
        grid.innerHTML = '<div class="empty-state"><div class="icon">💾</div><p>Nenhuma pasta NAS cadastrada. Clique em "➕ Nova Pasta" para começar.</p></div>';
        return;
    }
    grid.innerHTML = pastas.map(p => {
        const accessCount = (p.acessos || []).length;
        const caminhoCopy = (p.caminho_rede || '').replace(/'/g, "\\'");
        return `
        <div class="nas-card">
            <div class="nas-card-header">
                <div>
                    <div class="nas-card-name">💾 ${p.nome}</div>
                    ${p.caminho_rede ? `<div class="nas-card-path" onclick="navigator.clipboard.writeText('${caminhoCopy}');showMsg('✅ Caminho copiado','success')">${p.caminho_rede} 📋</div>` : ''}
                    ${p.descricao ? `<div class="nas-card-desc">${p.descricao}</div>` : ''}
                </div>
                <div style="display:flex;gap:6px;flex-shrink:0">
                    <button class="btn-card btn-card-edit" onclick="editarNASPasta(${p.id})">✏️</button>
                    <button class="btn-danger btn-sm" onclick="deletarNASPasta(${p.id})">🗑️</button>
                </div>
            </div>
            <div class="nas-acessos-section">
                <div class="email-users-header">
                    <span>👥 ${accessCount} usuário(s) com acesso</span>
                    <button class="btn-sm btn-glow" onclick="abrirModalNASAcesso(${p.id},'${p.nome.replace(/'/g, "\\'")}')">➕ Dar Acesso</button>
                </div>
                ${(p.acessos || []).map(a => `
                    <div class="nas-acesso-item">
                        <div class="nas-letra-badge">${a.letra_mapeada || '?:'}</div>
                        <div class="mini-avatar mini-avatar-sm">${a.user_nome ? a.user_nome[0] : '?'}</div>
                        <div style="flex:1">
                            <strong>${a.user_nome || '?'}</strong>
                            <span class="nas-perm-badge nas-perm-${(a.permissao || '').toLowerCase()}">${a.permissao === 'Admin' ? '👑 Admin' :
                a.permissao === 'Escrita' ? '✏️ Leitura/Escrita' : '📖 Leitura'
            }</span>
                        </div>
                        <button class="btn-danger btn-sm" onclick="removerNASAcesso(${a.id})">✕</button>
                    </div>`).join('') || '<div style="color:#546e7a;font-size:12px;margin-top:6px">Nenhum acesso configurado.</div>'}
            </div>
        </div>`;
    }).join('');
}

function abrirModalNASPasta(dados = null) {
    editingNASPastaId = null;
    document.getElementById('formNASPasta').reset();
    document.getElementById('modalNASTitle').textContent = '💾 Nova Pasta NAS';
    if (dados) {
        editingNASPastaId = dados.id;
        document.getElementById('modalNASTitle').textContent = '✏️ Editar Pasta NAS';
        document.getElementById('nasPastaId').value = dados.id;
        document.getElementById('npNome').value = dados.nome || '';
        document.getElementById('npCaminho').value = dados.caminho_rede || '';
        document.getElementById('npDescricao').value = dados.descricao || '';
        document.getElementById('npObs').value = dados.obs || '';
    }
    abrirModal('modalNASPasta');
}

async function editarNASPasta(id) {
    try {
        const p = await api(`/api/it/nas-pastas/${id}`);
        abrirModalNASPasta(p);
    } catch (e) { showMsg('❌ Erro ao carregar pasta', 'error'); }
}

async function salvarNASPasta(e) {
    e.preventDefault();
    const id = editingNASPastaId;
    const body = {
        nome: document.getElementById('npNome').value,
        caminho_rede: document.getElementById('npCaminho').value,
        descricao: document.getElementById('npDescricao').value,
        obs: document.getElementById('npObs').value,
    };
    try {
        if (id) { await api(`/api/it/nas-pastas/${id}`, 'PUT', body); }
        else { await api('/api/it/nas-pastas', 'POST', body); }
        showMsg('✅ Pasta salva!', 'success');
        fecharModal('modalNASPasta');
        carregarNASPastas();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

async function deletarNASPasta(id) {
    if (!confirm('Deletar esta pasta e todos os acessos vinculados?')) return;
    await api(`/api/it/nas-pastas/${id}`, 'DELETE');
    showMsg('🗑️ Pasta removida', 'info');
    carregarNASPastas();
}

async function abrirModalNASAcesso(pastaId, pastaNome) {
    nasAcessoPastaIdCurrent = pastaId;
    document.getElementById('formNASAcesso').reset();
    document.getElementById('nasAcessoPastaId').value = pastaId;
    document.getElementById('nasAcessoPastaDisplay').textContent = `💾 ${pastaNome}`;
    const users = await api('/api/it/users').catch(() => []);
    const sel = document.getElementById('naUserId');
    sel.innerHTML = '<option value="">— Selecione o usuário —</option>' +
        users.map(u => `<option value="${u.id}">${u.nome} (${u.setor || u.cargo || ''})</option>`).join('');
    abrirModal('modalNASAcesso');
}

async function salvarNASAcesso(e) {
    e.preventDefault();
    const pastaId = document.getElementById('nasAcessoPastaId').value;
    let letra = document.getElementById('naLetra').value.toUpperCase();
    if (letra && !letra.endsWith(':')) letra += ':';
    const body = {
        it_user_id: parseInt(document.getElementById('naUserId').value),
        letra_mapeada: letra,
        permissao: document.getElementById('naPermissao').value,
        obs: document.getElementById('naObs').value,
    };
    try {
        await api(`/api/it/nas-pastas/${pastaId}/acessos`, 'POST', body);
        showMsg('✅ Acesso concedido!', 'success');
        fecharModal('modalNASAcesso');
        carregarNASPastas();
    } catch (err) { showMsg('❌ ' + err.message, 'error'); }
}

async function removerNASAcesso(acessoId) {
    if (!confirm('Remover acesso deste usuário à pasta?')) return;
    await api(`/api/it/nas-acessos/${acessoId}`, 'DELETE');
    showMsg('✅ Acesso removido', 'info');
    carregarNASPastas();
}

// ======== IA ASSISTENTE ========
let iaHistorico = [];
let iaStatusBusy = false;

async function enviarMensagemIA() {
    const input = document.getElementById('iaInput');
    const msg = input.value.trim();
    if (!msg || iaStatusBusy) return;

    iaStatusBusy = true;

    input.value = '';
    input.disabled = true;
    const btn = document.getElementById('iaSendBtn');
    if (btn) btn.disabled = true;

    renderizarMsgIA('user', msg);

    // Mostra indicador de processamento
    const loadingId = 'ia-loading-' + Date.now();
    const chatBox = document.getElementById('iaChatBox');
    const aiMsgId = 'ai-msg-' + Date.now();

    chatBox.insertAdjacentHTML('beforeend', `
        <div class="ia-msg ai" id="${loadingId}">
            <div class="ia-avatar">🤖</div>
            <div class="ia-bubble">Processando...</div>
        </div>
    `);
    chatBox.scrollTop = chatBox.scrollHeight;

    let fullText = "";

    try {
        console.log("IA: Enviando pergunta...", msg);
        const response = await fetch('/api/ia/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pergunta: msg, historico: iaHistorico })
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Erro na comunicação com o servidor');
        }

        console.log("IA: Conexão estabelecida, aguardando stream...");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let isFirstToken = true;
        let bubble;
        let buffer = ""; // Buffer redundante para pacotes fragmentados

        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                console.log("IA: Stream fechado pelo servidor.");
                if (isFirstToken) console.error("IA: ERRO - Stream fechou sem enviar nenhum token de texto!");
                break;
            }

            const chunkRaw = decoder.decode(value, { stream: true });
            buffer += chunkRaw;

            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed) continue;

                if (trimmed.startsWith('data: ')) {
                    try {
                        const jsonStr = trimmed.substring(6);
                        const data = JSON.parse(jsonStr);

                        if (data.error) throw new Error(data.error);
                        if (data.text) {
                            if (isFirstToken) {
                                console.log("IA: Primeiro texto detectado! Removendo loading...");
                                if (document.getElementById(loadingId)) document.getElementById(loadingId).remove();
                                chatBox.insertAdjacentHTML('beforeend', `
                                    <div class="ia-msg ai" id="${aiMsgId}">
                                        <div class="ia-avatar">🤖</div>
                                        <div class="ia-bubble"></div>
                                    </div>
                                `);
                                bubble = document.getElementById(aiMsgId).querySelector('.ia-bubble');
                                isFirstToken = false;
                            }
                            fullText += data.text;
                            bubble.innerHTML = formatarMarkdownSimples(fullText);
                            chatBox.scrollTop = chatBox.scrollHeight;
                        }
                    } catch (e) {
                        console.error("IA: Erro ao parsear JSON:", e, trimmed);
                    }
                } else {
                    console.warn("IA: Linha ignorada (não inicia com data:):", trimmed);
                }
            }
        }

        // Atualiza histórico local ao concluir
        iaHistorico.push({ role: 'user', content: msg });
        iaHistorico.push({ role: 'assistant', content: fullText });
        if (iaHistorico.length > 20) iaHistorico = iaHistorico.slice(-20);

    } catch (err) {
        if (document.getElementById(loadingId)) document.getElementById(loadingId).remove();
        renderizarMsgIA('ai', '❌ ' + err.message);
    } finally {
        iaStatusBusy = false;
        if (document.getElementById(loadingId)) document.getElementById(loadingId).remove();
        input.disabled = false;
        if (btn) btn.disabled = false;
        input.focus();
    }
}

function renderizarMsgIA(tipo, texto) {
    const chatBox = document.getElementById('iaChatBox');
    const html = `
        <div class="ia-msg ${tipo}">
            <div class="ia-avatar">${tipo === 'ai' ? '🤖' : '👤'}</div>
            <div class="ia-bubble">${formatarMarkdownSimples(texto)}</div>
        </div>
    `;
    chatBox.insertAdjacentHTML('beforeend', html);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function formatarMarkdownSimples(txt) {
    // Formatação básica para negrito e blocos de código que a IA costuma retornar
    return txt
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
        .replace(/```(.*?)```/gs, '<pre><code>$1</code></pre>')
        .replace(/`(.*?)`/g, '<code>$1</code>');
}

async function gerarAnaliseIA() {
    if (iaStatusBusy) return;
    iaStatusBusy = true;

    const chatBox = document.getElementById('iaChatBox');
    const loadingId = 'ia-loading-' + Date.now();
    const aiMsgId = 'ai-msg-' + Date.now();

    chatBox.insertAdjacentHTML('beforeend', `
        <div class="ia-msg ai" id="${loadingId}">
            <div class="ia-avatar">🤖</div>
            <div class="ia-bubble">✨ Iniciando análise completa do seu parque tecnológico... Por favor, aguarde.</div>
        </div>
    `);
    chatBox.scrollTop = chatBox.scrollHeight;

    let fullText = "### 📊 Parecer Sênior de TI:\n\n";

    try {
        const response = await fetch('/api/ia/analise');
        if (!response.ok) throw new Error('Erro ao gerar análise');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let isFirstToken = true;
        let bubble;
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed || !trimmed.startsWith('data: ')) continue;

                try {
                    const data = JSON.parse(trimmed.substring(6));
                    if (data.error) throw new Error(data.error);
                    if (data.text) {
                        if (isFirstToken) {
                            if (document.getElementById(loadingId)) document.getElementById(loadingId).remove();
                            chatBox.insertAdjacentHTML('beforeend', `
                                <div class="ia-msg ai" id="${aiMsgId}">
                                    <div class="ia-avatar">🤖</div>
                                    <div class="ia-bubble"></div>
                                </div>
                            `);
                            bubble = document.getElementById(aiMsgId).querySelector('.ia-bubble');
                            isFirstToken = false;
                        }
                        fullText += data.text;
                        bubble.innerHTML = formatarMarkdownSimples(fullText);
                        chatBox.scrollTop = chatBox.scrollHeight;
                    }
                } catch (e) {
                    console.warn("Fragmento em Análise ignorado:", trimmed);
                }
            }
        }
    } catch (err) {
        if (document.getElementById(loadingId)) document.getElementById(loadingId).remove();
        renderizarMsgIA('ai', '❌ ' + err.message);
    } finally {
        iaStatusBusy = false;
    }
}

function iaSugerir(frase) {
    document.getElementById('iaInput').value = frase;
    enviarMensagemIA();
}

function limparChatIA() {
    if (!confirm('Deseja limpar o histórico do chat?')) return;
    iaHistorico = [];
    document.getElementById('iaChatBox').innerHTML = `
        <div class="ia-msg ai">
            <div class="ia-avatar">🤖</div>
            <div class="ia-bubble">Histórico limpo. Como posso ajudar com sua infraestrutura agora?</div>
        </div>
    `;
}

function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    const btn = event.currentTarget;
    if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = '🙈';
    } else {
        input.type = 'password';
        btn.textContent = '👁️';
    }
}
