// Estado global
let itens = [];

// Inicialização
document.addEventListener('DOMContentLoaded', function() {
    setupModals();
    setupFilters();
    setupForms();
    carregarItens();
    carregarUsuario();
});

// Carrega usuário logado
async function carregarUsuario() {
    try {
        const response = await fetch('/usuario');
        if (response.ok) {
            const data = await response.json();
            document.getElementById('username').textContent = data.usuario;
            document.querySelector('.user-avatar').textContent = data.usuario[0].toUpperCase();
        }
    } catch (error) {
        console.error('Erro ao carregar usuário:', error);
    }
}

// Carrega itens do estoque
async function carregarItens() {
    try {
        showMessage('🔄 Carregando itens do estoque...', 'info');

        const response = await fetch('/api/estoque/itens');
        
        if (response.ok) {
            itens = await response.json();
            renderizarTabela();
            atualizarEstatisticas();
            showMessage('✅ Itens carregados com sucesso', 'success');
        } else {
            throw new Error('Erro ao carregar itens');
        }
    } catch (error) {
        console.error('Erro:', error);
        showMessage('❌ Erro ao carregar itens do estoque', 'error');
    }
}

// Renderiza tabela de itens
function renderizarTabela() {
    const tbody = document.getElementById('estoqueTableBody');
    
    if (itens.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="12" style="text-align: center; padding: 40px; color: #78909c;">
                    📦 Nenhum item cadastrado no estoque
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = itens.map(item => `
        <tr>
            <td><strong>${item.id}</strong></td>
            <td>${item.tipo_item || '-'}</td>
            <td>${item.categoria || '-'}</td>
            <td>${item.descricao || '-'}</td>
            <td>${item.marca || '-'}${item.modelo ? ' / ' + item.modelo : ''}</td>
            <td>${item.numero_serie || '-'}</td>
            <td>${item.tombo_patrimonio || '-'}</td>
            <td>
                <strong ${item.quantidade <= item.quantidade_minima ? 'style="color: #e57373;"' : ''}>
                    ${item.quantidade || 0}
                </strong> ${item.unidade || 'UN'}
            </td>
            <td><span class="status-badge status-${(item.status || 'disponivel').toLowerCase().replace(' ', '-').normalize('NFD').replace(/[\u0300-\u036f]/g, '')}">${item.status || 'Disponível'}</span></td>
            <td><span class="status-badge condicao-${(item.condicao || 'novo').toLowerCase()}">${item.condicao || 'Novo'}</span></td>
            <td>${item.localizacao || '-'}</td>
            <td>
                <button class="action-btn view" onclick="verDetalhes('${item.id}')">👁️</button>
                <button class="action-btn" onclick="editarItem('${item.id}')">✏️</button>
                <button class="action-btn delete" onclick="confirmarDelete('${item.id}')">🗑️</button>
            </td>
        </tr>
    `).join('');

    // Aplica filtros após renderizar
    aplicarFiltros();
}

// Atualiza estatísticas
function atualizarEstatisticas() {
    const total = itens.length;
    const disponiveis = itens.filter(i => i.status === 'Disponível').length;
    const emUso = itens.filter(i => i.status === 'Em Uso').length;
    const baixoEstoque = itens.filter(i => i.quantidade <= i.quantidade_minima).length;

    document.getElementById('statTotal').textContent = total;
    document.getElementById('statDisponiveis').textContent = disponiveis;
    document.getElementById('statEmUso').textContent = emUso;
    document.getElementById('statBaixoEstoque').textContent = baixoEstoque;
}

// Setup de filtros
function setupFilters() {
    const searchInput = document.getElementById('searchInput');
    const filterTipo = document.getElementById('filterTipo');
    const filterCategoria = document.getElementById('filterCategoria');
    const filterStatus = document.getElementById('filterStatus');
    const filterCondicao = document.getElementById('filterCondicao');

    searchInput.addEventListener('input', aplicarFiltros);
    filterTipo.addEventListener('change', aplicarFiltros);
    filterCategoria.addEventListener('change', aplicarFiltros);
    filterStatus.addEventListener('change', aplicarFiltros);
    filterCondicao.addEventListener('change', aplicarFiltros);
}

// Aplica filtros
function aplicarFiltros() {
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const tipo = document.getElementById('filterTipo').value;
    const categoria = document.getElementById('filterCategoria').value;
    const status = document.getElementById('filterStatus').value;
    const condicao = document.getElementById('filterCondicao').value;

    const rows = document.querySelectorAll('#estoqueTableBody tr');
    
    rows.forEach(row => {
        const cells = row.querySelectorAll('td');
        if (cells.length < 2) return; // Skip empty state row
        
        const rowText = Array.from(cells).map(cell => cell.textContent.toLowerCase()).join(' ');
        const rowTipo = cells[1].textContent;
        const rowCategoria = cells[2].textContent;
        const rowStatus = cells[8].textContent;
        const rowCondicao = cells[9].textContent;

        let showRow = true;

        if (searchTerm && !rowText.includes(searchTerm)) {
            showRow = false;
        }

        if (tipo && rowTipo !== tipo) {
            showRow = false;
        }

        if (categoria && rowCategoria !== categoria) {
            showRow = false;
        }

        if (status && rowStatus !== status) {
            showRow = false;
        }

        if (condicao && rowCondicao !== condicao) {
            showRow = false;
        }

        row.style.display = showRow ? '' : 'none';
    });
}

// Limpar filtros
function limparFiltros() {
    document.getElementById('searchInput').value = '';
    document.getElementById('filterTipo').value = '';
    document.getElementById('filterCategoria').value = '';
    document.getElementById('filterStatus').value = '';
    document.getElementById('filterCondicao').value = '';
    aplicarFiltros();
}

// Setup de modals
function setupModals() {
    const modals = document.querySelectorAll('.modal');
    
    modals.forEach(modal => {
        const closeBtn = modal.querySelector('.close');
        
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                modal.style.display = 'none';
            });
        }
        
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    });
}

// Setup de formulários
function setupForms() {
    document.getElementById('formNovoItem').addEventListener('submit', criarItem);
    document.getElementById('formEditarItem').addEventListener('submit', salvarEdicaoItem);
}

// Abre modal novo item
function abrirModalNovoItem() {
    document.getElementById('modalNovoItem').style.display = 'block';
    document.getElementById('formNovoItem').reset();
}

// Fecha modal
function fecharModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

// Cria novo item
async function criarItem(e) {
    e.preventDefault();
    
    try {
        const formData = {
            tipo_item: document.getElementById('tipo_item').value,
            categoria: document.getElementById('categoria').value,
            descricao: document.getElementById('descricao').value,
            marca: document.getElementById('marca').value,
            modelo: document.getElementById('modelo').value,
            fabricante: document.getElementById('fabricante').value,
            numero_serie: document.getElementById('numero_serie').value,
            tombo_patrimonio: document.getElementById('tombo_patrimonio').value,
            chave_produto: document.getElementById('chave_produto').value,
            versao: document.getElementById('versao').value,
            quantidade: parseInt(document.getElementById('quantidade').value) || 0,
            quantidade_minima: parseInt(document.getElementById('quantidade_minima').value) || 1,
            unidade: document.getElementById('unidade').value,
            numero_nfe: document.getElementById('numero_nfe').value,
            chave_nfe: document.getElementById('chave_nfe').value,
            data_nfe: document.getElementById('data_nfe').value,
            valor_nfe: document.getElementById('valor_nfe').value,
            fornecedor: document.getElementById('fornecedor').value,
            status: document.getElementById('status').value,
            condicao: document.getElementById('condicao').value,
            localizacao: document.getElementById('localizacao').value,
            empresa: document.getElementById('empresa').value,
            garantia_meses: parseInt(document.getElementById('garantia_meses').value) || null,
            data_fim_garantia: document.getElementById('data_fim_garantia').value
        };

        const response = await fetch('/api/estoque/itens', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        if (response.ok) {
            const result = await response.json();
            showMessage(`✅ Item #${result.id} criado com sucesso`, 'success');
            fecharModal('modalNovoItem');
            document.getElementById('formNovoItem').reset();
            carregarItens();
        } else {
            throw new Error('Erro ao criar item');
        }
    } catch (error) {
        console.error('Erro:', error);
        showMessage('❌ Erro ao criar item', 'error');
    }
}

// Editar item
async function editarItem(itemId) {
    try {
        const response = await fetch(`/api/estoque/itens/${itemId}`);
        
        if (response.ok) {
            const item = await response.json();
            
            // Preenche form de edição
            document.getElementById('editId').value = item.id;
            document.getElementById('editTipo_item').value = item.tipo_item || '';
            document.getElementById('editCategoria').value = item.categoria || '';
            document.getElementById('editDescricao').value = item.descricao || '';
            document.getElementById('editMarca').value = item.marca || '';
            document.getElementById('editModelo').value = item.modelo || '';
            document.getElementById('editFabricante').value = item.fabricante || '';
            document.getElementById('editNumero_serie').value = item.numero_serie || '';
            document.getElementById('editTombo_patrimonio').value = item.tombo_patrimonio || '';
            document.getElementById('editChave_produto').value = item.chave_produto || '';
            document.getElementById('editVersao').value = item.versao || '';
            document.getElementById('editQuantidade').value = item.quantidade || 0;
            document.getElementById('editQuantidade_minima').value = item.quantidade_minima || 1;
            document.getElementById('editUnidade').value = item.unidade || 'UN';
            document.getElementById('editStatus').value = item.status || 'Disponível';
            document.getElementById('editCondicao').value = item.condicao || 'Novo';
            document.getElementById('editLocalizacao').value = item.localizacao || '';
            document.getElementById('editEmpresa').value = item.empresa || '';
            
            // Abre modal
            document.getElementById('modalEditarItem').style.display = 'block';
        } else {
            throw new Error('Erro ao carregar dados do item');
        }
    } catch (error) {
        console.error('Erro:', error);
        showMessage('❌ Erro ao carregar item para edição', 'error');
    }
}

// Salva edição do item
async function salvarEdicaoItem(e) {
    e.preventDefault();
    
    try {
        const itemId = document.getElementById('editId').value;
        const formData = {
            tipo_item: document.getElementById('editTipo_item').value,
            categoria: document.getElementById('editCategoria').value,
            descricao: document.getElementById('editDescricao').value,
            marca: document.getElementById('editMarca').value,
            modelo: document.getElementById('editModelo').value,
            fabricante: document.getElementById('editFabricante').value,
            numero_serie: document.getElementById('editNumero_serie').value,
            tombo_patrimonio: document.getElementById('editTombo_patrimonio').value,
            chave_produto: document.getElementById('editChave_produto').value,
            versao: document.getElementById('editVersao').value,
            quantidade: parseInt(document.getElementById('editQuantidade').value) || 0,
            quantidade_minima: parseInt(document.getElementById('editQuantidade_minima').value) || 1,
            unidade: document.getElementById('editUnidade').value,
            status: document.getElementById('editStatus').value,
            condicao: document.getElementById('editCondicao').value,
            localizacao: document.getElementById('editLocalizacao').value,
            empresa: document.getElementById('editEmpresa').value
        };

        const response = await fetch(`/api/estoque/itens/${itemId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });

        if (response.ok) {
            showMessage(`✅ Item #${itemId} atualizado com sucesso`, 'success');
            fecharModal('modalEditarItem');
            carregarItens();
        } else {
            const errorData = await response.json().catch(() => ({}));
            const errorMessage = errorData.error || `Erro ${response.status}: ${response.statusText}`;
            throw new Error(errorMessage);
        }
    } catch (error) {
        console.error('Erro:', error);
        showMessage(`❌ Erro ao atualizar item: ${error.message}`, 'error');
    }
}

// Ver detalhes do item
async function verDetalhes(itemId) {
    try {
        const response = await fetch(`/api/estoque/itens/${itemId}`);
        
        if (response.ok) {
            const item = await response.json();
            
            const detalhesHTML = `
                <div class="detalhes-grid">
                    <div class="detalhe-item">
                        <div class="detalhe-label">ID</div>
                        <div class="detalhe-value">${item.id}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Tipo</div>
                        <div class="detalhe-value">${item.tipo_item || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Categoria</div>
                        <div class="detalhe-value">${item.categoria || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Descrição</div>
                        <div class="detalhe-value">${item.descricao || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Marca</div>
                        <div class="detalhe-value">${item.marca || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Modelo</div>
                        <div class="detalhe-value">${item.modelo || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Fabricante</div>
                        <div class="detalhe-value">${item.fabricante || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Número de Série</div>
                        <div class="detalhe-value">${item.numero_serie || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Tombo/Patrimônio</div>
                        <div class="detalhe-value">${item.tombo_patrimonio || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Chave do Produto</div>
                        <div class="detalhe-value">${item.chave_produto || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Versão</div>
                        <div class="detalhe-value">${item.versao || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Quantidade</div>
                        <div class="detalhe-value"><strong>${item.quantidade || 0}</strong> ${item.unidade || 'UN'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Quantidade Mínima</div>
                        <div class="detalhe-value">${item.quantidade_minima || '-'} ${item.unidade || 'UN'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Status</div>
                        <div class="detalhe-value"><span class="status-badge status-${(item.status || 'disponivel').toLowerCase().replace(' ', '-').normalize('NFD').replace(/[\u0300-\u036f]/g, '')}">${item.status || 'Disponível'}</span></div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Condição</div>
                        <div class="detalhe-value"><span class="status-badge condicao-${(item.condicao || 'novo').toLowerCase()}">${item.condicao || 'Novo'}</span></div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Localização</div>
                        <div class="detalhe-value">${item.localizacao || '-'}</div>
                    </div>
                    <div class="detalhe-item">
                        <div class="detalhe-label">Empresa</div>
                        <div class="detalhe-value">${item.empresa || '-'}</div>
                    </div>
                    ${item.numero_nfe ? `
                    <div class="detalhe-item">
                        <div class="detalhe-label">Número NFe</div>
                        <div class="detalhe-value">${item.numero_nfe}</div>
                    </div>
                    ` : ''}
                    ${item.fornecedor ? `
                    <div class="detalhe-item">
                        <div class="detalhe-label">Fornecedor</div>
                        <div class="detalhe-value">${item.fornecedor}</div>
                    </div>
                    ` : ''}
                    ${item.valor_nfe ? `
                    <div class="detalhe-item">
                        <div class="detalhe-label">Valor NFe</div>
                        <div class="detalhe-value">${item.valor_nfe}</div>
                    </div>
                    ` : ''}
                    ${item.garantia_meses ? `
                    <div class="detalhe-item">
                        <div class="detalhe-label">Garantia</div>
                        <div class="detalhe-value">${item.garantia_meses} meses</div>
                    </div>
                    ` : ''}
                    ${item.data_entrada ? `
                    <div class="detalhe-item">
                        <div class="detalhe-label">Data de Entrada</div>
                        <div class="detalhe-value">${new Date(item.data_entrada).toLocaleDateString('pt-BR')}</div>
                    </div>
                    ` : ''}
                </div>
            `;
            
            document.getElementById('detalhesContent').innerHTML = detalhesHTML;
            document.getElementById('modalDetalhes').style.display = 'block';
        } else {
            throw new Error('Erro ao carregar detalhes do item');
        }
    } catch (error) {
        console.error('Erro:', error);
        showMessage('❌ Erro ao carregar detalhes do item', 'error');
    }
}

// Confirma exclusão do item
function confirmarDelete(itemId) {
    if (confirm('Tem certeza que deseja excluir este item? Esta ação não pode ser desfeita.')) {
        deletarItem(itemId);
    }
}

// Deleta item
async function deletarItem(itemId) {
    try {
        const response = await fetch(`/api/estoque/itens/${itemId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showMessage(`✅ Item #${itemId} excluído com sucesso`, 'success');
            carregarItens();
        } else {
            throw new Error('Erro ao deletar item');
        }
    } catch (error) {
        console.error('Erro:', error);
        showMessage('❌ Erro ao deletar item', 'error');
    }
}

// Abre modal de movimentações
function abrirModalMovimentacao() {
    // Aqui você pode carregar o histórico de movimentações
    document.getElementById('modalMovimentacao').style.display = 'block';
    carregarMovimentacoes();
}

// Carrega movimentações
async function carregarMovimentacoes() {
    try {
        const response = await fetch('/api/estoque/movimentacoes');
        
        if (response.ok) {
            const movimentacoes = await response.json();
            const lista = document.getElementById('movimentacoesList');
            
            if (movimentacoes.length === 0) {
                lista.innerHTML = '<p style="text-align: center; color: #78909c;">Nenhuma movimentação registrada</p>';
                return;
            }
            
            lista.innerHTML = movimentacoes.map(mov => `
                <div class="movimentacao-item">
                    <div class="movimentacao-header">
                        <div class="movimentacao-tipo">${mov.tipo || 'Movimentação'}</div>
                        <div class="movimentacao-data">${mov.data ? new Date(mov.data).toLocaleDateString('pt-BR') : '-'}</div>
                    </div>
                    <div class="movimentacao-descricao">
                        Item: <strong>${mov.item_id}</strong> - ${mov.descricao || 'Sem descrição'}
                    </div>
                </div>
            `).join('');
        }
    } catch (error) {
        console.error('Erro:', error);
        document.getElementById('movimentacoesList').innerHTML = '<p style="text-align: center; color: #e57373;">Erro ao carregar movimentações</p>';
    }
}

// Exportar Excel (CSV)
function exportarExcel() {
    window.location.href = '/api/estoque/export/excel';
}

// Mostra mensagens
function showMessage(message, type = 'info') {
    const messageArea = document.getElementById('messageArea');
    let className = 'info';
    
    if (type === 'success') className = 'success';
    if (type === 'error') className = 'error';
    
    messageArea.innerHTML = `<div class="message ${className}">${message}</div>`;
    
    // Remove mensagem após 5 segundos
    setTimeout(() => {
        messageArea.innerHTML = '';
    }, 5000);
}

// Atualização automática a cada 60 segundos
setInterval(() => {
    carregarItens();
}, 60000);

// Atalhos do teclado
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + N = Novo item
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
        e.preventDefault();
        abrirModalNovoItem();
    }
    
    // ESC = Fechar modals
    if (e.key === 'Escape') {
        const modals = document.querySelectorAll('.modal');
        modals.forEach(modal => {
            if (modal.style.display === 'block') {
                modal.style.display = 'none';
            }
        });
    }
});