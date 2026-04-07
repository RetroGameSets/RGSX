        // ===== VARIABLES GLOBALES =====
        let currentPlatform = null;
        let currentGameSort = 'name_asc';  // Type de tri actuel: 'name_asc', 'name_desc', 'size_asc', 'size_desc'
        let currentGames = [];  // Stocke les jeux actuels pour le tri
        const loggedUnparsedSizeTexts = new Set();
        let lastProgressUpdate = Date.now();
        let autoRefreshTimeout = null;
        let progressInterval = null;
        let queueInterval = null;
        let translations = {};  // Contiendra toutes les traductions
        let trackedDownloads = (() => {
            // Charger depuis localStorage ou initialiser
            try {
                const stored = localStorage.getItem('trackedDownloads');
                return stored ? JSON.parse(stored) : {};
            } catch (e) {
                return {};
            }
        })();
        
        // ===== TOAST NOTIFICATIONS =====
        function showToast(message, type = 'info', duration = 3000) {
            // Créer le conteneur de toasts s'il n'existe pas
            let toastContainer = document.getElementById('toast-container');
            if (!toastContainer) {
                toastContainer = document.createElement('div');
                toastContainer.id = 'toast-container';
                toastContainer.style.cssText = `
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    z-index: 9999;
                    pointer-events: none;
                    max-width: 400px;
                `;
                document.body.appendChild(toastContainer);
            }
            
            // Créer l'élément toast
            const toast = document.createElement('div');
            const colors = {
                'success': '#28a745',
                'error': '#dc3545',
                'warning': '#ffc107',
                'info': '#17a2b8'
            };
            const icons = {
                'success': '✅',
                'error': '❌',
                'warning': '⚠️',
                'info': 'ℹ️'
            };
            
            toast.style.cssText = `
                background: ${colors[type] || colors['info']};
                color: white;
                padding: 16px 20px;
                border-radius: 8px;
                margin-bottom: 10px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                animation: slideIn 0.3s ease-out;
                pointer-events: auto;
                font-weight: 500;
                max-width: 100%;
                word-wrap: break-word;
            `;
            
            toast.textContent = `${icons[type] || ''} ${message}`;
            toastContainer.appendChild(toast);
            
            // Auto-remove après duration
            if (duration > 0) {
                setTimeout(() => {
                    toast.style.animation = 'slideOut 0.3s ease-in';
                    setTimeout(() => {
                        toast.remove();
                    }, 300);
                }, duration);
            }
            
            return toast;
        }
        
        // Ajouter les styles d'animation s'ils n'existent pas
        if (!document.getElementById('toast-styles')) {
            const style = document.createElement('style');
            style.id = 'toast-styles';
            style.textContent = `
                @keyframes slideIn {
                    from {
                        transform: translateX(400px);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
                @keyframes slideOut {
                    from {
                        transform: translateX(0);
                        opacity: 1;
                    }
                    to {
                        transform: translateX(400px);
                        opacity: 0;
                    }
                }
            `;
            document.head.appendChild(style);
        }
        
        // Modal pour afficher les messages support avec formatage
        function showSupportModal(title, message) {
            // Remplacer les \n littéraux par de vrais retours à la ligne
            message = message.replace(/\\n/g, '\n');
            
            // Créer la modal
            const modal = document.createElement('div');
            modal.className = 'support-modal';
            
            const modalContent = document.createElement('div');
            modalContent.className = 'support-modal-content';
            
            // Titre
            const titleElement = document.createElement('h2');
            titleElement.textContent = title;
            
            // Message avec retours à la ligne préservés
            const messageElement = document.createElement('div');
            messageElement.className = 'support-modal-message';
            messageElement.textContent = message;
            
            // Bouton OK
            const okButton = document.createElement('button');
            okButton.textContent = 'OK';
            okButton.onclick = () => {
                modal.style.animation = 'fadeOut 0.2s ease-in';
                setTimeout(() => modal.remove(), 200);
            };
            
            // Assembler la modal
            modalContent.appendChild(titleElement);
            modalContent.appendChild(messageElement);
            modalContent.appendChild(okButton);
            modal.appendChild(modalContent);
            
            // Ajouter au DOM
            document.body.appendChild(modal);
            
            // Fermer en cliquant sur le fond
            modal.onclick = (e) => {
                if (e.target === modal) {
                    modal.style.animation = 'fadeOut 0.2s ease-in';
                    setTimeout(() => modal.remove(), 200);
                }
            };
        }
        
        // Charger les traductions au démarrage
        async function loadTranslations() {
            try {
                const response = await fetch('/api/translations');
                const data = await response.json();
                if (data.success) {
                    translations = data.translations;
                    console.log('Traductions chargées:', data.language, Object.keys(translations).length, 'clés');
                }
            } catch (error) {
                console.error('Erreur chargement traductions:', error);
            }
        }
        
        // Fonction helper pour obtenir une traduction avec paramètres
        function t(key, ...params) {
            let text = translations[key] || key;
            // Remplacer {0}, {1}, etc. par les paramètres (sans regex pour éviter les erreurs)
            params.forEach((param, index) => {
                text = text.split('{' + index + '}').join(param);
            });
            // Convertir les \\n en vrais sauts de ligne pour les alertes
            text = text.replace(/\\\\n/g, '\\n');
            return text;
        }
        
        // Fonction pour obtenir les unités de taille selon la langue
        function getSizeUnits() {
            // Détecter la langue depuis les traductions chargées ou le navigateur
            const lang = translations['_language'] || navigator.language.substring(0, 2);
            // Français utilise o, Ko, Mo, Go, To
            // Autres langues utilisent B, KB, MB, GB, TB
            return lang === 'fr' ? ['o', 'Ko', 'Mo', 'Go', 'To', 'Po'] : ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
        }
        
        // Fonction pour obtenir l'unité de vitesse selon la langue
        function getSpeedUnit() {
            const lang = translations['_language'] || navigator.language.substring(0, 2);
            return lang === 'fr' ? 'Mo/s' : 'MB/s';
        }
        
        // Fonction pour formater une taille en octets
        function formatSize(bytes) {
            if (!bytes || bytes === 0) return 'N/A';
            const units = getSizeUnits();
            let size = bytes;
            let unitIndex = 0;
            while (size >= 1024 && unitIndex < units.length - 1) {
                size /= 1024;
                unitIndex++;
            }
            return `${size.toFixed(1)} ${units[unitIndex]}`;
        }

        function parseSizeToBytes(sizeText) {
            if (!sizeText) return 0;

            const rawText = String(sizeText).trim();
            let normalized = rawText.replace(/octets?/gi, 'B');

            if (normalized.includes(',') && normalized.includes('.')) {
                normalized = normalized.replace(/,/g, '');
            } else if (normalized.includes(',')) {
                normalized = normalized.replace(',', '.');
            }

            const match = normalized.match(/^([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)/);
            if (!match) {
                if (!loggedUnparsedSizeTexts.has(rawText)) {
                    loggedUnparsedSizeTexts.add(rawText);
                    console.warn('[RGSX][sort] Taille non interpretable:', rawText);
                }
                return 0;
            }

            const value = parseFloat(match[1]);
            if (Number.isNaN(value)) return 0;

            const unit = match[2].toLowerCase();
            const multipliers = {
                b: 1,
                byte: 1,
                bytes: 1,
                o: 1,
                k: 1024,
                ko: 1024,
                kb: 1024,
                kib: 1024,
                kio: 1024,
                m: 1024 ** 2,
                mo: 1024 ** 2,
                mb: 1024 ** 2,
                mib: 1024 ** 2,
                mio: 1024 ** 2,
                g: 1024 ** 3,
                go: 1024 ** 3,
                gb: 1024 ** 3,
                gib: 1024 ** 3,
                gio: 1024 ** 3,
                t: 1024 ** 4,
                to: 1024 ** 4,
                tb: 1024 ** 4,
                tib: 1024 ** 4,
                tio: 1024 ** 4,
                p: 1024 ** 5,
                po: 1024 ** 5,
                pb: 1024 ** 5,
                pib: 1024 ** 5,
                pio: 1024 ** 5,
            };

            if (!multipliers[unit]) {
                if (!loggedUnparsedSizeTexts.has(rawText)) {
                    loggedUnparsedSizeTexts.add(rawText);
                    console.warn('[RGSX][sort] Unite de taille non supportee:', rawText, '->', unit);
                }
                return 0;
            }

            return Math.round(value * multipliers[unit]);
        }
        
        // Appliquer les traductions à tous les éléments marqués
        function applyTranslations() {
            // Mettre à jour le titre de la page
            document.title = '🎮 ' + t('web_title');
            
            // Traduire tous les éléments avec data-translate
            document.querySelectorAll('[data-translate]').forEach(el => {
                const key = el.getAttribute('data-translate');
                el.textContent = t(key);
            });
            
            // Traduire tous les attributs title avec data-translate-title
            document.querySelectorAll('[data-translate-title]').forEach(el => {
                const key = el.getAttribute('data-translate-title');
                el.title = t(key);
            });
            
            // Traduire tous les placeholders avec data-translate-placeholder
            document.querySelectorAll('[data-translate-placeholder]').forEach(el => {
                const key = el.getAttribute('data-translate-placeholder');
                el.placeholder = t(key);
            });
        }
        
        // ===== FONCTIONS UTILITAIRES =====
               
        // Fonction pour mettre à jour la liste des jeux (clear cache)
        async function updateGamesList() {
            if (!confirm(t('web_update_title') + '\\n\\nThis will clear the cache and reload all games data.\\nThis may take a few moments.')) {
                return;
            }
            
            try {
                // Afficher un message de chargement
                const container = document.querySelector('.content');
                const originalContent = container.innerHTML;
                container.innerHTML = '<div class="loading" style="padding: 100px; text-align: center;"><h2>🔄 ' + t('web_update_title') + '</h2><p>' + t('web_update_message') + '</p><p style="margin-top: 20px; font-size: 0.9em; color: #666;">' + t('web_update_wait') + '</p></div>';
                
                const response = await fetch('/api/update-cache');
                const data = await response.json();
                
                if (data.success) {
                    // Attendre 2 secondes pour que le serveur se recharge
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    
                    // Recharger la page
                    location.reload();
                } else {
                    alert(t('web_error') + ': ' + (data.error || t('web_error_unknown')));
                    container.innerHTML = originalContent;
                }
            } catch (error) {
                alert(t('web_error_update', error.message));
                location.reload();
            }
        }
        
        // Détecter les blocages de progression et rafraîchir automatiquement
        function checkProgressTimeout() {
            const now = Date.now();
            const timeSinceLastUpdate = now - lastProgressUpdate;
            
            // Si pas de mise à jour depuis 30 secondes et qu'on est sur l'onglet téléchargements
            const downloadsTab = document.getElementById('downloads-content');
            if (downloadsTab && downloadsTab.style.display !== 'none') {
                if (timeSinceLastUpdate > 30000) {
                    console.warn('[AUTO-REFRESH] Aucune mise à jour depuis 30s, rafraîchissement...');
                    location.reload();
                }
            }
        }
        
        // Restaurer un état
        function restoreState(state) {
            if (state.tab) {
                showTab(state.tab, false);
                
                if (state.tab === 'platforms' && state.platform) {
                    loadGames(state.platform, false);
                }
            }
        }
        
        // Afficher un onglet
        function showTab(tab, updateHistory = true) {
            // Arrêter les intervalles existants
            if (progressInterval) {
                clearInterval(progressInterval);
                progressInterval = null;
            }
            if (queueInterval) {
                clearInterval(queueInterval);
                queueInterval = null;
            }
            
            // Mettre à jour l'UI - tabs desktop
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            const tabButtons = Array.from(document.querySelectorAll('.tab'));
            const tabNames = ['platforms', 'downloads', 'queue', 'history', 'settings'];
            const tabIndex = tabNames.indexOf(tab);
            if (tabIndex >= 0 && tabButtons[tabIndex]) {
                tabButtons[tabIndex].classList.add('active');
            }
            
            // Mettre à jour l'UI - tabs mobile
            document.querySelectorAll('.mobile-tab').forEach(t => t.classList.remove('active'));
            const mobileTabButtons = Array.from(document.querySelectorAll('.mobile-tab'));
            if (tabIndex >= 0 && mobileTabButtons[tabIndex]) {
                mobileTabButtons[tabIndex].classList.add('active');
            }
            
            document.querySelectorAll('.content > div').forEach(c => c.style.display = 'none');
            document.getElementById(tab + '-content').style.display = 'block';
            
            // Mettre à jour l'URL et l'historique du navigateur
            if (updateHistory) {
                const url = tab === 'platforms' ? '/' : `/${tab}`;
                const state = { tab: tab };
                window.history.pushState(state, '', url);
            }
            
            if (tab === 'platforms') loadPlatforms();
            else if (tab === 'downloads') loadProgress();
            else if (tab === 'queue') {
                loadQueue();
                // Rafraîchir la queue toutes les 2 secondes
                queueInterval = setInterval(loadQueue, 2000);
            }
            else if (tab === 'history') loadHistory();
            else if (tab === 'settings') loadSettings();
        }
        
        // ===== EVENT LISTENERS =====
        
        // Vérifier toutes les 5 secondes pour auto-refresh
        setInterval(checkProgressTimeout, 5000);
        
        // Gérer le bouton retour du navigateur
        window.addEventListener('popstate', function(event) {
            if (event.state) {
                restoreState(event.state);
            }
        });
        
        // Restaurer l'état depuis l'URL au chargement
        window.addEventListener('DOMContentLoaded', function() {
            // Load saved filters first
            loadSavedFilters();
            
            const path = window.location.pathname;
            
            if (path.startsWith('/platform/')) {
                const platformName = decodeURIComponent(path.split('/platform/')[1]);
                loadGames(platformName, false);
            } else if (path === '/downloads') {
                showTab('downloads', false);
            } else if (path === '/history') {
                showTab('history', false);
            } else if (path === '/settings') {
                showTab('settings', false);
            } else {
                // État initial - définir l'historique sans recharger
                window.history.replaceState({ tab: 'platforms' }, '', '/');
                loadPlatforms();
            }
        });
        
        // ===== FONCTIONS PRINCIPALES =====
        
        // Variables globales pour la recherche
        let searchTimeout = null;
        let currentSearchTerm = '';
        
        // Filtrer les plateformes avec recherche universelle
        async function filterPlatforms(searchTerm) {
            currentSearchTerm = searchTerm.trim();
            const term = currentSearchTerm.toLowerCase();
            
            // Afficher/masquer le bouton clear
            const clearBtn = document.getElementById('clear-platforms-search');
            if (clearBtn) {
                clearBtn.style.display = searchTerm ? 'block' : 'none';
            }
            
            // Si la recherche est vide, afficher toutes les plateformes normalement
            if (!term) {
                const cards = document.querySelectorAll('.platform-card');
                cards.forEach(card => card.style.display = '');
                // Masquer les résultats de recherche
                const searchResults = document.getElementById('search-results');
                if (searchResults) searchResults.style.display = 'none';
                const platformGrid = document.querySelector('.platform-grid');
                if (platformGrid) platformGrid.style.display = 'grid';
                return;
            }
            
            // Debounce pour éviter trop de requêtes
            if (searchTimeout) clearTimeout(searchTimeout);
            
            searchTimeout = setTimeout(async () => {
                try {
                    // Appeler l'API de recherche universelle
                    const response = await fetch('/api/search?q=' + encodeURIComponent(term));
                    const data = await response.json();
                    
                    if (!data.success) throw new Error(data.error);
                    
                    const results = data.results;
                    const platformsMatch = results.platforms || [];
                    const gamesMatch = results.games || [];
                    
                    // Masquer la grille normale des plateformes
                    const platformGrid = document.querySelector('.platform-grid');
                    if (platformGrid) platformGrid.style.display = 'none';
                    
                    // Créer ou mettre à jour la zone de résultats
                    let searchResults = document.getElementById('search-results');
                    if (!searchResults) {
                        searchResults = document.createElement('div');
                        searchResults.id = 'search-results';
                        searchResults.style.cssText = 'margin-top: 20px;';
                        const container = document.getElementById('platforms-content');
                        container.appendChild(searchResults);
                    }
                    searchResults.style.display = 'block';
                    
                    // Construire le HTML des résultats
                    let html = '<div style="padding: 20px; background: #f9f9f9; border-radius: 8px;">';
                    
                    // Résumé
                    const totalResults = platformsMatch.length + gamesMatch.length;
                    html += `<h3 style="margin-bottom: 15px;">🔍 ${totalResults} ${t('web_search_results')} "${term}"</h3>`;
                    
                    if (totalResults === 0) {
                        html += `<p style="color: #666;">${t('web_no_results')}</p>`;
                    }
                    
                    // Afficher les systèmes correspondants
                    if (platformsMatch.length > 0) {
                        html += `<h4 style="margin-top: 20px; margin-bottom: 10px;">🎮 ${t('web_platforms')} (${platformsMatch.length})</h4>`;
                        html += '<div class="platform-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;">';
                        
                        platformsMatch.forEach(platform => {
                            const imageUrl = '/api/platform-image/' + encodeURIComponent(platform.platform_name);
                            html += `
                                <div class="platform-card" onclick='loadGames("${platform.platform_name.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}")'>
                                    <img src="${imageUrl}" alt="${platform.platform_name}" onerror="this.src='/favicon.ico'">
                                    <h3>${platform.platform_name}</h3>
                                    <p>${platform.games_count} ${t('web_games')}</p>
                                </div>
                            `;
                        });
                        
                        html += '</div>';
                    }
                    
                    // Afficher les jeux correspondants (groupés par système)
                    if (gamesMatch.length > 0) {
                        html += `<h4 style="margin-top: 20px; margin-bottom: 10px;">🎯 ${t('web_games')} (${gamesMatch.length})</h4>`;
                        
                        // Grouper les jeux par plateforme
                        const gamesByPlatform = {};
                        gamesMatch.forEach(game => {
                            if (!gamesByPlatform[game.platform]) {
                                gamesByPlatform[game.platform] = [];
                            }
                            gamesByPlatform[game.platform].push(game);
                        });
                        
                        // Afficher chaque groupe
                        for (const [platformName, games] of Object.entries(gamesByPlatform)) {
                            html += `
                                <div style="margin-bottom: 15px; background: white; padding: 15px; border-radius: 5px; border: 1px solid #ddd;">
                                    <h5 style="margin: 0 0 10px 0; color: #007bff; cursor: pointer;" onclick='loadGames("${platformName.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}")'>
                                        📁 ${platformName} (${games.length})
                                    </h5>
                                    <div style="display: flex; flex-direction: column; gap: 8px;">
                            `;
                            
                            games.forEach((game, idx) => {
                                const downloadTitle = t('web_download');
                                html += `
                                    <div class="search-game-item" style="padding: 15px; background: #f9f9f9; border-radius: 8px; transition: background 0.2s;">
                                        <div class="search-game-name" style="font-weight: 500; margin-bottom: 10px; word-wrap: break-word; overflow-wrap: break-word;">${game.game_name}</div>
                                        <div style="display: flex; justify-content: space-between; align-items: center;">
                                            ${game.size ? `<span style="background: #667eea; color: white; padding: 5px 10px; border-radius: 5px; font-size: 0.9em; white-space: nowrap;">${game.size}</span>` : '<span></span>'}
                                            <div class="download-btn-group" style="display: flex; gap: 4px;">
                                                <button class="download-btn" title="${downloadTitle} (now)" onclick='downloadGame("${platformName.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", "${game.game_name.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", null, "now")' style="background: transparent; color: #28a745; border: none; padding: 8px; border-radius: 5px; cursor: pointer; font-size: 1.5em; min-width: 40px;">⬇️</button>
                                                <button class="download-btn" title="${downloadTitle} (queue)" onclick='downloadGame("${platformName.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", "${game.game_name.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", null, "queue")' style="background: transparent; color: #28a745; border: none; padding: 8px; border-radius: 5px; cursor: pointer; font-size: 1.5em; min-width: 40px;">➕</button>
                                            </div>
                                        </div>
                                    </div>
                                `;
                            });
                            
                            html += `
                                    </div>
                                </div>
                            `;
                        }
                    }
                    
                    html += '</div>';
                    searchResults.innerHTML = html;
                    
                } catch (error) {
                    console.error('Erreur recherche:', error);
                    const searchResults = document.getElementById('search-results');
                    if (searchResults) {
                        searchResults.innerHTML = `<p style="color: red;">❌ ${t('web_error_search')}: ${error.message}</p>`;
                    }
                }
            }, 300); // Attendre 300ms après la dernière frappe
        }
        
        // Filter state: Map of region -> 'include' or 'exclude'
        let regionFilters = new Map();
        
        // Checkbox filter states (stored globally to restore after page changes)
        let savedHideNonRelease = false;
        let savedOneRomPerGame = false;
        let savedRegexMode = false;
        
        // Region priority order for "One ROM Per Game" (customizable)
        let regionPriorityOrder = JSON.parse(localStorage.getItem('regionPriorityOrder')) || 
            ['USA', 'Canada', 'Europe', 'France', 'Germany', 'Japan', 'Korea', 'World', 'Other'];
        
        // Save filters to backend
        async function saveFiltersToBackend() {
            try {
                const regionFiltersObj = {};
                regionFilters.forEach((mode, region) => {
                    regionFiltersObj[region] = mode;
                });
                
                // Update saved states from checkboxes if they exist
                if (document.getElementById('hide-non-release')) {
                    savedHideNonRelease = document.getElementById('hide-non-release').checked;
                }
                if (document.getElementById('one-rom-per-game')) {
                    savedOneRomPerGame = document.getElementById('one-rom-per-game').checked;
                }
                if (document.getElementById('regex-mode')) {
                    savedRegexMode = document.getElementById('regex-mode').checked;
                }
                
                const response = await fetch('/api/save_filters', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        region_filters: regionFiltersObj,
                        hide_non_release: savedHideNonRelease,
                        one_rom_per_game: savedOneRomPerGame,
                        regex_mode: savedRegexMode,
                        region_priority: regionPriorityOrder
                    })
                });
                
                const data = await response.json();
                if (!data.success) {
                    console.warn('Failed to save filters:', data.error);
                }
            } catch (error) {
                console.warn('Failed to save filters:', error);
            }
        }

        // Load saved filters from settings
        async function loadSavedFilters() {
            try {
                const response = await fetch('/api/settings');
                const data = await response.json();
                
                if (data.success && data.settings.game_filters) {
                    const filters = data.settings.game_filters;
                    
                    // Load region filters
                    if (filters.region_filters) {
                        regionFilters.clear();
                        Object.entries(filters.region_filters).forEach(([region, mode]) => {
                            regionFilters.set(region, mode);
                        });
                    }
                    
                    // Load region priority
                    if (filters.region_priority) {
                        regionPriorityOrder = filters.region_priority;
                        localStorage.setItem('regionPriorityOrder', JSON.stringify(regionPriorityOrder));
                    }
                    
                    // Save checkbox states to global variables
                    savedHideNonRelease = filters.hide_non_release || false;
                    savedOneRomPerGame = filters.one_rom_per_game || false;
                    savedRegexMode = filters.regex_mode || false;
                    
                    // Load checkboxes when they exist (in games view)
                    if (document.getElementById('hide-non-release')) {
                        document.getElementById('hide-non-release').checked = savedHideNonRelease;
                    }
                    if (document.getElementById('one-rom-per-game')) {
                        document.getElementById('one-rom-per-game').checked = savedOneRomPerGame;
                    }
                    if (document.getElementById('regex-mode')) {
                        document.getElementById('regex-mode').checked = savedRegexMode;
                    }
                }
            } catch (error) {
                console.warn('Failed to load saved filters:', error);
            }
        }
        
        // Restore filter button states in the UI
        function restoreFilterStates() {
            // Restore region button states
            regionFilters.forEach((mode, region) => {
                const btn = document.querySelector(`.region-btn[data-region="${region}"]`);
                if (btn) {
                    if (mode === 'include') {
                        btn.classList.add('active');
                        btn.classList.remove('excluded');
                    } else if (mode === 'exclude') {
                        btn.classList.remove('active');
                        btn.classList.add('excluded');
                    }
                }
            });
            
            // Restore checkbox states
            if (document.getElementById('hide-non-release')) {
                document.getElementById('hide-non-release').checked = savedHideNonRelease;
            }
            if (document.getElementById('one-rom-per-game')) {
                document.getElementById('one-rom-per-game').checked = savedOneRomPerGame;
            }
            if (document.getElementById('regex-mode')) {
                document.getElementById('regex-mode').checked = savedRegexMode;
            }
            
            // Apply filters to display the games correctly
            applyAllFilters();
        }


        // Helper: Extract region(s) from game name - returns array of regions
        function getGameRegions(gameName) {
            const name = gameName.toUpperCase();
            const regions = [];
            
            // Common region patterns - check all, not just first match
            // Handle both "(USA)" and "(USA, Europe)" formats
            if (name.includes('USA') || name.includes('US)')) regions.push('USA');
            if (name.includes('CANADA')) regions.push('Canada');
            if (name.includes('EUROPE') || name.includes('EU)')) regions.push('Europe');
            if (name.includes('FRANCE') || name.includes('FR)')) regions.push('France');
            if (name.includes('GERMANY') || name.includes('DE)')) regions.push('Germany');
            if (name.includes('JAPAN') || name.includes('JP)') || name.includes('JPN)')) regions.push('Japan');
            if (name.includes('KOREA') || name.includes('KR)')) regions.push('Korea');
            if (name.includes('WORLD')) regions.push('World');
            
            // Check for other regions (excluding the ones above)
            if (name.match(/\b(AUSTRALIA|ASIA|BRAZIL|CHINA|RUSSIA|SCANDINAVIA|SPAIN|ITALY)\b/)) {
                if (!regions.includes('Other')) regions.push('Other');
            }
            
            // If no region found, classify as Other
            if (regions.length === 0) regions.push('Other');
            
            // Debug log for multi-region games
            if (regions.length > 1 && gameName.includes('Game Guru')) {
                console.log('getGameRegions:', gameName, '->', regions);
            }
            
            return regions;
        }

        // Helper: Check if game is non-release version
        function isNonReleaseGame(gameName) {
            const name = gameName.toUpperCase();
            // Match parentheses or brackets containing these keywords
            // Using [^\)] instead of .* to avoid catastrophic backtracking
            const nonReleasePatterns = [
                /\([^\)]*BETA[^\)]*\)/,
                /\([^\)]*DEMO[^\)]*\)/,
                /\([^\)]*PROTO[^\)]*\)/,
                /\([^\)]*SAMPLE[^\)]*\)/,
                /\([^\)]*KIOSK[^\)]*\)/,
                /\([^\)]*PREVIEW[^\)]*\)/,
                /\([^\)]*TEST[^\)]*\)/,
                /\([^\)]*DEBUG[^\)]*\)/,
                /\([^\)]*ALPHA[^\)]*\)/,
                /\([^\)]*PRE-RELEASE[^\)]*\)/,
                /\([^\)]*PRERELEASE[^\)]*\)/,
                /\([^\)]*UNFINISHED[^\)]*\)/,
                /\([^\)]*WIP[^\)]*\)/,
                /\[[^\]]*BETA[^\]]*\]/,
                /\[[^\]]*DEMO[^\]]*\]/,
                /\[[^\]]*TEST[^\]]*\]/
            ];
            return nonReleasePatterns.some(pattern => pattern.test(name));
        }

        // Helper: Get base game name (strip regions, versions, etc. but preserve disc numbers)
        function getBaseGameName(gameName) {
            let base = gameName;

            // Remove file extensions
            base = base.replace(/\.(zip|7z|rar|gz|iso)$/i, '');

            // Extract disc/disk number if present (before removing parentheses)
            let discInfo = '';
            const discMatch = base.match(/\(Dis[ck]\s*(\d+)\)/i) ||
                            base.match(/\[Dis[ck]\s*(\d+)\]/i) ||
                            base.match(/Dis[ck]\s*(\d+)/i) ||
                            base.match(/\(CD\s*(\d+)\)/i) ||
                            base.match(/CD\s*(\d+)/i);
            if (discMatch) {
                discInfo = ` Disc ${discMatch[1]}`;
            }

            // Remove parenthetical content (regions, languages, versions, etc.)
            base = base.replace(/\([^)]*\)/g, '');
            base = base.replace(/\[[^\]]*\]/g, '');

            // Normalize whitespace
            base = base.replace(/\s+/g, ' ').trim();

            // Re-append disc info
            base = base + discInfo;

            return base;
        }

        // Helper: Get region priority for one-rom-per-game (lower = better)
        function getRegionPriority(gameName) {
            const name = gameName.toUpperCase();
            
            // Find the first matching region in priority order
            for (let i = 0; i < regionPriorityOrder.length; i++) {
                const region = regionPriorityOrder[i].toUpperCase();
                if (region === 'USA' && name.includes('USA')) return i;
                if (region === 'CANADA' && name.includes('CANADA')) return i;
                if (region === 'WORLD' && name.includes('WORLD')) return i;
                if (region === 'EUROPE' && (name.includes('EUROPE') || name.includes('EU)'))) return i;
                if (region === 'FRANCE' && (name.includes('FRANCE') || name.includes('FR)'))) return i;
                if (region === 'GERMANY' && (name.includes('GERMANY') || name.includes('DE)'))) return i;
                if (region === 'JAPAN' && (name.includes('JAPAN') || name.includes('JP)') || name.includes('JPN)'))) return i;
                if (region === 'KOREA' && (name.includes('KOREA') || name.includes('KR)'))) return i;
            }
            
            return regionPriorityOrder.length; // Other regions (lowest priority)
        }
        
        // Save region priority order to localStorage
        function saveRegionPriorityOrder() {
            localStorage.setItem('regionPriorityOrder', JSON.stringify(regionPriorityOrder));
            updateRegionPriorityDisplay();
        }
        
        // Update the display of current region priority order
        function updateRegionPriorityDisplay() {
            const display = document.getElementById('region-priority-display');
            if (display) {
                display.textContent = regionPriorityOrder.join(' → ');
            }
        }
        
        // Move region up in priority (decrease index = higher priority)
        function moveRegionUp(region) {
            const idx = regionPriorityOrder.indexOf(region);
            if (idx > 0) {
                [regionPriorityOrder[idx], regionPriorityOrder[idx-1]] = 
                [regionPriorityOrder[idx-1], regionPriorityOrder[idx]];
                saveRegionPriorityOrder();
                renderRegionPriorityConfig();
                saveFiltersToBackend();
            }
        }
        
        // Move region down in priority (increase index = lower priority)
        function moveRegionDown(region) {
            const idx = regionPriorityOrder.indexOf(region);
            if (idx >= 0 && idx < regionPriorityOrder.length - 1) {
                [regionPriorityOrder[idx], regionPriorityOrder[idx+1]] = 
                [regionPriorityOrder[idx+1], regionPriorityOrder[idx]];
                saveRegionPriorityOrder();
                renderRegionPriorityConfig();
                saveFiltersToBackend();
            }
        }
        
        // Reset region priority to default
        function resetRegionPriority() {
            regionPriorityOrder = ['USA', 'Canada', 'Europe', 'France', 'Germany', 'Japan', 'Korea', 'World', 'Other'];
            saveRegionPriorityOrder();
            renderRegionPriorityConfig();
            saveFiltersToBackend();
        }
        
        // Render region priority configuration UI
        function renderRegionPriorityConfig() {
            const container = document.getElementById('region-priority-config');
            if (!container) return;
            
            let html = '<div style="margin-bottom: 10px;"><strong>Configure Region Priority Order:</strong></div>';
            html += '<div style="display: flex; flex-direction: column; gap: 6px;">';
            
            regionPriorityOrder.forEach((region, idx) => {
                html += `
                    <div style="display: flex; align-items: center; gap: 8px; padding: 6px; background: #f5f5f5; border-radius: 4px;">
                        <span style="font-weight: bold; color: #666; min-width: 25px;">${idx + 1}.</span>
                        <span style="flex: 1; font-weight: 500;">${region}</span>
                        <button onclick="moveRegionUp('${region}')" 
                                style="padding: 4px 8px; border: 1px solid #ccc; background: white; cursor: pointer; border-radius: 3px; font-size: 14px;"
                                ${idx === 0 ? 'disabled' : ''}>🔼</button>
                        <button onclick="moveRegionDown('${region}')" 
                                style="padding: 4px 8px; border: 1px solid #ccc; background: white; cursor: pointer; border-radius: 3px; font-size: 14px;"
                                ${idx === regionPriorityOrder.length - 1 ? 'disabled' : ''}>🔽</button>
                    </div>
                `;
            });
            
            html += '</div>';
            html += '<div style="margin-top: 10px; display: flex; gap: 8px;">';
            html += '<button onclick="resetRegionPriority()" style="padding: 6px 12px; background: #666; color: white; border: none; border-radius: 4px; cursor: pointer;">Reset to Default</button>';
            html += '<button onclick="closeRegionPriorityModal()" style="padding: 6px 12px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer;">Done</button>';
            html += '</div>';
            
            container.innerHTML = html;
            updateRegionPriorityDisplay();
        }
        
        // Show region priority configuration modal
        function showRegionPriorityConfig() {
            const modal = document.getElementById('region-priority-modal');
            if (modal) {
                modal.style.display = 'flex';
                renderRegionPriorityConfig();
            }
        }
        
        // Close region priority configuration modal
        function closeRegionPriorityModal() {
            const modal = document.getElementById('region-priority-modal');
            if (modal) {
                modal.style.display = 'none';
            }
            applyAllFilters(); // Re-apply filters with new priority
        }

        // Toggle region filter: none → include (green) → exclude (red) → none
        function toggleRegionFilter(region) {
            const btn = document.querySelector(`.region-btn[data-region="${region}"]`);

            if (!regionFilters.has(region)) {
                // None → Include
                regionFilters.set(region, 'include');
                if (btn) {
                    btn.classList.add('active');
                    btn.classList.remove('excluded');
                }
            } else if (regionFilters.get(region) === 'include') {
                // Include → Exclude
                regionFilters.set(region, 'exclude');
                if (btn) {
                    btn.classList.remove('active');
                    btn.classList.add('excluded');
                }
            } else {
                // Exclude → None
                regionFilters.delete(region);
                if (btn) {
                    btn.classList.remove('active');
                    btn.classList.remove('excluded');
                }
            }

            applyAllFilters();
            saveFiltersToBackend();
        }

        // Apply all filters
        function applyAllFilters() {
            const searchInput = document.getElementById('game-search');
            const searchTerm = searchInput ? searchInput.value : '';
            const hideNonRelease = document.getElementById('hide-non-release')?.checked || savedHideNonRelease;
            const regexMode = document.getElementById('regex-mode')?.checked || savedRegexMode;

            const items = document.querySelectorAll('.game-item');
            let visibleCount = 0;
            let hiddenByRegion = 0;
            let hiddenByNonRelease = 0;
            let hiddenBySearch = 0;

            // Prepare search pattern
            let searchPattern = null;
            if (searchTerm && regexMode) {
                try {
                    searchPattern = new RegExp(searchTerm, 'i');
                } catch (e) {
                    // Invalid regex, fall back to plain text
                    searchPattern = null;
                }
            }

            items.forEach(item => {
                const name = item.querySelector('.game-name').textContent;
                let visible = true;

                // Apply search filter
                if (searchTerm) {
                    if (regexMode && searchPattern) {
                        if (!searchPattern.test(name)) {
                            visible = false;
                            hiddenBySearch++;
                        }
                    } else {
                        if (!name.toLowerCase().includes(searchTerm.toLowerCase())) {
                            visible = false;
                            hiddenBySearch++;
                        }
                    }
                }

                // Apply region filters
                if (visible && regionFilters.size > 0) {
                    const gameRegions = getGameRegions(name);

                    // Get included and excluded regions
                    const includedRegions = Array.from(regionFilters.entries())
                        .filter(([_, mode]) => mode === 'include')
                        .map(([region, _]) => region);
                    const excludedRegions = Array.from(regionFilters.entries())
                        .filter(([_, mode]) => mode === 'exclude')
                        .map(([region, _]) => region);

                    // Debug log for Game Guru
                    if (name.includes('Game Guru')) {
                        console.log('Filtering Game Guru:', {
                            name,
                            gameRegions,
                            includedRegions,
                            excludedRegions,
                            willShow: gameRegions.some(region => includedRegions.includes(region))
                        });
                    }

                    // If there are include filters, game must match at least one of them
                    if (includedRegions.length > 0) {
                        if (!gameRegions.some(region => includedRegions.includes(region))) {
                            visible = false;
                            hiddenByRegion++;
                        }
                    }

                    // If there are exclude filters, game must NOT match any of them
                    if (visible && excludedRegions.length > 0) {
                        if (gameRegions.some(region => excludedRegions.includes(region))) {
                            visible = false;
                            hiddenByRegion++;
                        }
                    }
                }

                // Apply non-release filter
                if (visible && hideNonRelease) {
                    if (isNonReleaseGame(name)) {
                        visible = false;
                        hiddenByNonRelease++;
                    }
                }

                item.style.display = visible ? '' : 'none';
                if (visible) visibleCount++;
            });

            // Apply one-rom-per-game filter (after other filters)
            const oneRomPerGame = document.getElementById('one-rom-per-game')?.checked || savedOneRomPerGame;
            if (oneRomPerGame) {
                // Group currently visible games by base name
                const gameGroups = new Map();

                items.forEach(item => {
                    if (item.style.display !== 'none') {
                        const name = item.querySelector('.game-name').textContent;
                        const baseName = getBaseGameName(name);

                        if (!gameGroups.has(baseName)) {
                            gameGroups.set(baseName, []);
                        }
                        gameGroups.get(baseName).push({ item, name });
                    }
                });

                // For each group, show only best region
                let hiddenByDuplicates = 0;
                gameGroups.forEach((games, baseName) => {
                    if (games.length > 1) {
                        // Sort by region priority (lower = better)
                        games.sort((a, b) => getRegionPriority(a.name) - getRegionPriority(b.name));

                        // Hide all except the best one
                        games.forEach((game, idx) => {
                            if (idx > 0) {
                                game.item.style.display = 'none';
                                visibleCount--;
                                hiddenByDuplicates++;
                            }
                        });
                    }
                });
            }

            // Update clear button
            const clearBtn = document.getElementById('clear-games-search');
            if (clearBtn) {
                clearBtn.style.display = searchTerm ? 'block' : 'none';
            }

            // Update filter status
            const statusDiv = document.getElementById('filter-status');
            if (statusDiv) {
                let statusParts = [`Showing ${visibleCount} of ${items.length} games`];

                if (regionFilters.size > 0) {
                    const included = Array.from(regionFilters.entries())
                        .filter(([_, mode]) => mode === 'include')
                        .map(([region, _]) => region);
                    const excluded = Array.from(regionFilters.entries())
                        .filter(([_, mode]) => mode === 'exclude')
                        .map(([region, _]) => region);

                    if (included.length > 0) {
                        statusParts.push(`Including: ${included.join(', ')}`);
                    }
                    if (excluded.length > 0) {
                        statusParts.push(`Excluding: ${excluded.join(', ')}`);
                    }
                }

                if (hideNonRelease) {
                    statusParts.push(`Hiding demos/betas/protos`);
                }
                if (regexMode && searchTerm) {
                    statusParts.push(`Regex mode`);
                }
                statusDiv.textContent = statusParts.join(' • ');
            }

            return visibleCount;
        }

        // Legacy function for backwards compatibility
        function filterGames(searchTerm) {
            return applyAllFilters();
        }
        
        // Trier les jeux
        function sortGames(sortType) {
            currentGameSort = sortType;
            const items = Array.from(document.querySelectorAll('.game-item'));
            const gamesList = document.querySelector('.games-list');

            if (!gamesList) {
                console.warn('[RGSX][sort] .games-list introuvable pour le tri', sortType);
                return;
            }

            const shouldLogSizeSort = sortType === 'size_asc' || sortType === 'size_desc';
            const getSizeInBytes = (sizeElem) => {
                if (!sizeElem) return 0;
                return parseSizeToBytes(sizeElem.textContent);
            };

            if (shouldLogSizeSort) {
                const previewBefore = items.slice(0, 5).map(item => {
                    const sizeText = item.querySelector('.game-size')?.textContent?.trim() || '';
                    return {
                        name: item.querySelector('.game-name')?.textContent?.trim() || '',
                        sizeText,
                        sizeBytes: getSizeInBytes(item.querySelector('.game-size')),
                    };
                });
                const zeroSizedCount = items.filter(item => {
                    const sizeElem = item.querySelector('.game-size');
                    return sizeElem && getSizeInBytes(sizeElem) === 0;
                }).length;
                console.debug('[RGSX][sort] Debut tri taille', {
                    sortType,
                    totalItems: items.length,
                    zeroSizedCount,
                    previewBefore,
                });
            }
            
            // Trier les éléments
            items.sort((a, b) => {
                const nameA = a.querySelector('.game-name').textContent.toLowerCase();
                const nameB = b.querySelector('.game-name').textContent.toLowerCase();
                const sizeElemA = a.querySelector('.game-size');
                const sizeElemB = b.querySelector('.game-size');
                
                switch(sortType) {
                    case 'name_asc':
                        return nameA.localeCompare(nameB);
                    case 'name_desc':
                        return nameB.localeCompare(nameA);
                    case 'size_asc':
                        return getSizeInBytes(sizeElemA) - getSizeInBytes(sizeElemB);
                    case 'size_desc':
                        return getSizeInBytes(sizeElemB) - getSizeInBytes(sizeElemA);
                    default:
                        return 0;
                }
            });
            
            // Réafficher les éléments dans l'ordre
            gamesList.innerHTML = '';
            items.forEach(item => {
                gamesList.appendChild(item);
            });

            if (shouldLogSizeSort) {
                const previewAfter = items.slice(0, 5).map(item => ({
                    name: item.querySelector('.game-name')?.textContent?.trim() || '',
                    sizeText: item.querySelector('.game-size')?.textContent?.trim() || '',
                    sizeBytes: getSizeInBytes(item.querySelector('.game-size')),
                }));
                console.debug('[RGSX][sort] Fin tri taille', {
                    sortType,
                    previewAfter,
                });
            }
            
            // Mettre à jour les boutons de tri
            document.querySelectorAll('.sort-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelector(`[data-sort="${sortType}"]`)?.classList.add('active');
        }
        
        // Charger les plateformes
        async function loadPlatforms() {
            const container = document.getElementById('platforms-content');
            container.innerHTML = '<div class="loading">⏳ ' + t('web_loading_platforms') + '</div>';
            
            try {
                const response = await fetch('/api/platforms');
                const data = await response.json();
                
                if (!data.success) throw new Error(data.error);
                
                if (data.platforms.length === 0) {
                    container.innerHTML = '<p>' + t('web_no_platforms') + '</p>';
                    return;
                }
                
                // Construire le HTML avec les traductions
                let searchPlaceholder = t('web_search_platform');
                const platformImageCacheBuster = Date.now();
                let html = `
                    <div class="search-box">
                        <input type="text" id="platform-search" placeholder="🔍 ${searchPlaceholder}" 
                               oninput="filterPlatforms(this.value)">
                        <button class="clear-search" id="clear-platforms-search" onclick="document.getElementById('platform-search').value=''; filterPlatforms('');">✕</button>
                        <span class="search-icon">🔍</span>
                    </div>
                    <div class="platform-grid">`;
                
                // Ajouter chaque plateforme
                data.platforms.forEach(p => {
                    let gameCountText = t('web_game_count', '📦', p.games_count || 0);
                    html += `
                        <div class="platform-card" onclick='loadGames("${p.platform_name.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}")'>
                            <img src="/api/image/${encodeURIComponent(p.platform_name)}?v=${platformImageCacheBuster}" 
                                 alt="${p.platform_name}"
                                 onerror="this.src='/api/image/default?v=${platformImageCacheBuster}'">
                            <h3>${p.platform_name}</h3>
                            <div class="count">${gameCountText}</div>
                        </div>
                    `;
                });
                
                html += '</div>';
                container.innerHTML = html;
                
            } catch (error) {
                let errorMsg = t('web_error');
                container.innerHTML = `<p style="color:red;">${errorMsg}: ${error.message}</p>`;
            }
        }
        
        // Charger les jeux d'une plateforme
        async function loadGames(platform, updateHistory = true) {
            currentPlatform = platform;
            const container = document.getElementById('platforms-content');
            container.innerHTML = '<div class="loading">⏳ ' + t('web_loading_games') + '</div>';
            
            // Mettre à jour l'URL et l'historique
            if (updateHistory) {
                const url = `/platform/${encodeURIComponent(platform)}`;
                const state = { tab: 'platforms', platform: platform };
                window.history.pushState(state, '', url);
            }
            
            try {
                const response = await fetch('/api/games/' + encodeURIComponent(platform));
                const data = await response.json();
                
                if (!data.success) throw new Error(data.error);
                
                // Construire le HTML avec les traductions
                let backText = t('web_back_platforms');
                let gameCountText = t('web_game_count', '', data.count);
                let searchPlaceholder = t('web_search_game');
                let downloadTitle = t('web_download');
                let sortLabel = t('web_sort');
                let sortNameAsc = t('web_sort_name_asc');
                let sortNameDesc = t('web_sort_name_desc');
                let sortSizeAsc = t('web_sort_size_asc');
                let sortSizeDesc = t('web_sort_size_desc');
                
                let html = `
                    <button class="back-btn" onclick="goBackToPlatforms()">← ${backText}</button>
                    <h2>${platform} ${gameCountText}</h2>
                    <div class="search-box">
                        <input type="text" id="game-search" placeholder="🔍 ${searchPlaceholder}"
                               oninput="applyAllFilters()">
                        <button class="clear-search" id="clear-games-search" onclick="document.getElementById('game-search').value=''; applyAllFilters();">✕</button>
                        <span class="search-icon">🔍</span>
                    </div>
                    <div class="filter-section">
                        <div class="filter-row">
                            <span class="filter-label">${t('web_filter_region')}:</span>
                            <button class="region-btn" data-region="USA" onclick="toggleRegionFilter('USA')"><img src="https://images.emojiterra.com/google/noto-emoji/unicode-16.0/color/svg/1f1fa-1f1f8.svg" style="width:16px;height:16px" /> USA</button>
                            <button class="region-btn" data-region="Canada" onclick="toggleRegionFilter('Canada')"><img src="https://images.emojiterra.com/google/noto-emoji/unicode-16.0/color/svg/1f1e8-1f1e6.svg" style="width:16px;height:16px" /> Canada</button>
                            <button class="region-btn" data-region="Europe" onclick="toggleRegionFilter('Europe')"><img src="https://images.emojiterra.com/google/noto-emoji/unicode-16.0/color/svg/1f1ea-1f1fa.svg" style="width:16px;height:16px" /> Europe</button>
                            <button class="region-btn" data-region="France" onclick="toggleRegionFilter('France')"><img src="https://images.emojiterra.com/google/noto-emoji/unicode-16.0/color/svg/1f1eb-1f1f7.svg" style="width:16px;height:16px" /> France</button>
                            <button class="region-btn" data-region="Germany" onclick="toggleRegionFilter('Germany')"><img src="https://images.emojiterra.com/google/noto-emoji/unicode-16.0/color/svg/1f1e9-1f1ea.svg" style="width:16px;height:16px" /> Germany</button>
                            <button class="region-btn" data-region="Japan" onclick="toggleRegionFilter('Japan')"><img src="https://images.emojiterra.com/google/noto-emoji/unicode-16.0/color/svg/1f1ef-1f1f5.svg" style="width:16px;height:16px" /> Japan</button>
                            <button class="region-btn" data-region="Korea" onclick="toggleRegionFilter('Korea')"><img src="https://images.emojiterra.com/google/noto-emoji/unicode-16.0/color/svg/1f1f0-1f1f7.svg" style="width:16px;height:16px" /> Korea</button>
                            <button class="region-btn" data-region="World" onclick="toggleRegionFilter('World')">🌍 World</button>
                            <button class="region-btn" data-region="Other" onclick="toggleRegionFilter('Other')">🌐 Other</button>
                        </div>
                        <div class="filter-row">
                            <label class="filter-checkbox">
                                <input type="checkbox" id="hide-non-release" onchange="applyAllFilters(); saveFiltersToBackend();">
                                <span>${t('web_filter_hide_non_release')}</span>
                            </label>
                            <label class="filter-checkbox">
                                <input type="checkbox" id="regex-mode" onchange="applyAllFilters(); saveFiltersToBackend();">
                                <span>${t('web_filter_regex_mode')}</span>
                            </label>
                            <label class="filter-checkbox">
                                <input type="checkbox" id="one-rom-per-game" onchange="applyAllFilters(); saveFiltersToBackend();">
                                <span>${t('web_filter_one_rom_per_game')} (<span id="region-priority-display">USA → Canada → World → Europe → Japan → Other</span>)</span>
                                <button onclick="showRegionPriorityConfig()" style="margin-left: 8px; padding: 2px 8px; font-size: 0.9em; background: #666; color: white; border: none; border-radius: 3px; cursor: pointer;" title="${t('web_filter_configure_priority')}">⚙️</button>
                            </label>
                        </div>
                    </div>
                    <div style="margin-top: 12px; margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap;">
                        <span style="font-weight: bold; align-self: center;">${sortLabel}:</span>
                        <button class="sort-btn active" data-sort="name_asc" onclick="sortGames('name_asc')" title="${sortNameAsc}">${sortNameAsc}</button>
                        <button class="sort-btn" data-sort="name_desc" onclick="sortGames('name_desc')" title="${sortNameDesc}">${sortNameDesc}</button>
                        <button class="sort-btn" data-sort="size_asc" onclick="sortGames('size_asc')" title="${sortSizeAsc}">${sortSizeAsc}</button>
                        <button class="sort-btn" data-sort="size_desc" onclick="sortGames('size_desc')" title="${sortSizeDesc}">${sortSizeDesc}</button>
                    </div>
                    <div id="filter-status" style="margin-bottom: 8px; font-size: 0.9em; color: #666;"></div>
                    <div class="games-list">`;
                
                // Ajouter chaque jeu
                data.games.forEach((g, idx) => {
                    html += `
                        <div class="game-item">
                            <span class="game-name">${g.name}</span>
                            ${g.size ? `<span class="game-size">${g.size}</span>` : ''}
                            <div class="download-btn-group" style="display: flex; gap: 4px;">
                                <button class="download-btn" title="${downloadTitle} (now)" onclick='downloadGame("${platform.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", "${g.name.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", ${idx}, "now")'>⬇️</button>
                                <button class="download-btn" title="${downloadTitle} (queue)" onclick='downloadGame("${platform.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", "${g.name.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", ${idx}, "queue")' style="background: #e0e0e0; color: #333;">➕</button>
                            </div>
                        </div>
                    `;
                });
                
                html += `
                    </div>
                `;
                container.innerHTML = html;
                
                // Restore filter states from loaded settings
                restoreFilterStates();
                
                // Appliquer le tri par défaut (A-Z)
                sortGames(currentGameSort);
                
            } catch (error) {
                let backText = t('web_back');
                let errorMsg = t('web_error');
                container.innerHTML = `
                    <button class="back-btn" onclick="goBackToPlatforms()">← ${backText}</button>
                    <p style="color:red;">${errorMsg}: ${error.message}</p>
                `;
            }
        }
        
        // Retour aux plateformes avec historique
        function goBackToPlatforms() {
            window.history.pushState({ tab: 'platforms' }, '', '/');
            loadPlatforms();
        }
        
        // Télécharger un jeu
        async function downloadGame(platform, gameName, gameIndex) {
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = '⏳';
            btn.title = t('web_download') + '...';
            const mode = arguments.length > 3 ? arguments[3] : 'now';
            try {
                // Préparer le body de la requête
                const requestBody = { platform: platform };
                if (typeof gameIndex === 'number' && gameIndex >= 0) {
                    requestBody.game_index = gameIndex;
                } else {
                    requestBody.game_name = gameName;
                }
                requestBody.mode = mode;
                const response = await fetch('/api/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });
                const data = await response.json();
                if (data.success) {
                    btn.textContent = '✅';
                    btn.title = t('web_download') + ' ✓';
                    btn.style.color = '#28a745';
                    
                    // Afficher un toast de succès (pas de redirection de page)
                    const toastMsg = mode === 'queue' 
                        ? `📋 "${gameName}" ${t('web_added_to_queue')}`
                        : `⬇️ ${t('web_downloading')}: "${gameName}"`;
                    showToast(toastMsg, 'success', 3000);
                    
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                btn.textContent = '❌';
                btn.title = t('web_error');
                btn.style.color = '#dc3545';
                showToast(`Erreur: ${error.message}`, 'error', 5000);
            } finally {
                setTimeout(() => {
                    btn.disabled = false;
                    btn.textContent = '⬇️';
                    btn.title = t('web_download');
                    btn.style.color = '';
                }, 3000);
            }
        }
        
        // Annuler un téléchargement
        async function cancelDownload(url, btn) {
            if (!confirm(t('web_confirm_cancel'))) {
                return;
            }
            
            btn.disabled = true;
            btn.textContent = '⏳';
            
            try {
                const response = await fetch('/api/cancel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    btn.textContent = '✅';
                    btn.style.color = '#28a745';
                    
                    // Recharger la liste après un court délai
                    setTimeout(() => {
                        loadProgress();
                    }, 500);
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                btn.textContent = '❌';
                btn.style.color = '#dc3545';
                alert(t('web_error_download', error.message));
                btn.disabled = false;
            }
        }
        
        // Charger la progression
        async function loadProgress(autoRefresh = true) {
            const container = document.getElementById('downloads-content');
            
            // Arrêter l'ancien interval si existant
            if (progressInterval) {
                clearInterval(progressInterval);
                progressInterval = null;
            }
            
            try {
                const response = await fetch('/api/progress');
                const data = await response.json();
                
                // Mettre à jour le timestamp de dernière mise à jour
                lastProgressUpdate = Date.now();
                
                console.log('[DEBUG] /api/progress response:', data);
                console.log('[DEBUG] downloads keys:', Object.keys(data.downloads || {}));
                
                if (!data.success) throw new Error(data.error);
                
                const downloads = Object.entries(data.downloads);
                
                if (downloads.length === 0) {
                    container.innerHTML = '<p>' + t('web_no_downloads') + '</p>';
                    return;
                }
                
                container.innerHTML = downloads.map(([url, info]) => {
                    const percent = info.progress_percent || 0;
                    const downloaded = info.downloaded_size || 0;
                    const total = info.total_size || 0;
                    const status = info.status || 'En cours';
                    const speed = info.speed || 0;
                    
                    // Utiliser game_name si disponible, sinon extraire de l'URL
                    let fileName = info.game_name || t('web_downloading');
                    if (!info.game_name) {
                        try {
                            fileName = decodeURIComponent(url.split('/').pop());
                        } catch (e) {
                            fileName = url.split('/').pop();
                        }
                    }
                    
                    // Afficher la plateforme si disponible
                    const platformInfo = info.platform ? ' (' + info.platform + ')' : '';
                    
                    return `
                        <div class="info-item">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <strong>📥 ${fileName}${platformInfo}</strong>
                                <button class="btn-action" onclick='cancelDownload("${url.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", this)' title="${t('web_cancel')}">
                                    ❌
                                </button>
                            </div>
                            <div style="margin-top: 10px;">
                                <div style="background: #e0e0e0; border-radius: 10px; height: 20px; overflow: hidden;">
                                    <div style="background: ${percent >= 100 ? '#28a745' : '#667eea'}; height: 100%; width: ${Math.min(percent, 100)}%; transition: width 0.3s;"></div>
                                </div>
                                <div style="display: flex; justify-content: space-between; margin-top: 5px; font-size: 0.9em;">
                                    <span>${status} - ${percent.toFixed(1)}%</span>
                                    <span>${speed > 0 ? speed.toFixed(2) + ' ' + getSpeedUnit() : ''}</span>
                                </div>
                                ${total > 0 ? `<div style="font-size: 0.85em; color: #666;">${formatSize(downloaded)} / ${formatSize(total)}</div>` : ''}
                                <div style="margin-top: 3px; font-size: 0.85em; color: #666;">
                                    📅 ${t('web_started')}: ${info.timestamp || 'N/A'}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
                
                // Rafraîchir automatiquement toutes les 500ms pour progression fluide
                // Créer le setInterval seulement si autoRefresh est true ET qu'il n'existe pas déjà
                if (autoRefresh && downloads.length > 0 && !progressInterval) {
                    progressInterval = setInterval(async () => {
                        const downloadsTab = document.getElementById('downloads-content');
                        if (downloadsTab && downloadsTab.style.display !== 'none') {
                            // Rafraîchir juste les données sans recréer le setInterval
                            try {
                                const response = await fetch('/api/progress');
                                const data = await response.json();
                                
                                // Mettre à jour le timestamp
                                lastProgressUpdate = Date.now();
                                
                                if (!data.success) throw new Error(data.error);
                                
                                const downloads = Object.entries(data.downloads);
                                
                                if (downloads.length === 0) {
                                    container.innerHTML = '<p>' + t('web_no_downloads') + '</p>';
                                    clearInterval(progressInterval);
                                    progressInterval = null;
                                    return;
                                }
                                
                                container.innerHTML = downloads.map(([url, info]) => {
                                    const percent = info.progress_percent || 0;
                                    const downloaded = info.downloaded_size || 0;
                                    const total = info.total_size || 0;
                                    const status = info.status || t('web_in_progress');
                                    const speed = info.speed || 0;
                                    
                                    let fileName = info.game_name || t('web_downloading');
                                    if (!info.game_name) {
                                        try {
                                            fileName = decodeURIComponent(url.split('/').pop());
                                        } catch (e) {
                                            fileName = url.split('/').pop();
                                        }
                                    }
                                    
                                    const platformInfo = info.platform ? ' (' + info.platform + ')' : '';
                                    
                                    return `
                                        <div class="info-item">
                                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                                <strong>📥 ${fileName}${platformInfo}</strong>
                                                <button class="btn-action" onclick='cancelDownload("${url.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", this)' title="${t('web_cancel')}">
                                                    ❌
                                                </button>
                                            </div>
                                            <div style="margin-top: 10px;">
                                                <div style="background: #e0e0e0; border-radius: 10px; height: 20px; overflow: hidden;">
                                                    <div style="background: ${percent >= 100 ? '#28a745' : '#667eea'}; height: 100%; width: ${Math.min(percent, 100)}%; transition: width 0.3s;"></div>
                                                </div>
                                                <div style="display: flex; justify-content: space-between; margin-top: 5px; font-size: 0.9em;">
                                                    <span>${status} - ${percent.toFixed(1)}%</span>
                                                    <span>${speed > 0 ? speed.toFixed(2) + ' ' + getSpeedUnit() : ''}</span>
                                                </div>
                                                ${total > 0 ? `<div style="font-size: 0.85em; color: #666;">${formatSize(downloaded)} / ${formatSize(total)}</div>` : ''}
                                                <div style="margin-top: 3px; font-size: 0.85em; color: #666;">
                                                    📅 ${t('web_started')}: ${info.timestamp || 'N/A'}
                                                </div>
                                            </div>
                                        </div>
                                    `;
                                }).join('');
                            } catch (error) {
                                console.error('[ERROR] Rafraîchissement progression:', error);
                            }
                        } else {
                            clearInterval(progressInterval);
                            progressInterval = null;
                        }
                    }, 500);
                }
            } catch (error) {
                container.innerHTML = `<p style="color:red;">Erreur: ${error.message}</p>`;
            }
        }
        
        // Charger la file d'attente
        async function loadQueue() {
            const container = document.getElementById('queue-content');
            
            try {
                const response = await fetch('/api/queue');
                const data = await response.json();
                
                if (!data.success) throw new Error(data.error);
                
                const queue = data.queue || [];
                const isActive = data.active || false;
                
                let html = '<div>';
                
                // Afficher l'état actif
                if (isActive) {
                    html += '<div style="background: #e8f5e9; border: 1px solid #4caf50; padding: 15px; border-radius: 5px; margin-bottom: 15px;">';
                    html += '<strong style="color: #2e7d32;">⏳ ' + t('web_queue_active_download') + '</strong>';
                    html += '</div>';
                } else {
                    html += '<div style="background: #f5f5f5; border: 1px solid #ccc; padding: 15px; border-radius: 5px; margin-bottom: 15px;">';
                    html += '<strong style="color: #666;">✓ ' + t('web_queue_no_active') + '</strong>';
                    html += '</div>';
                }
                
                // Afficher la queue
                if (queue.length === 0) {
                    html += '<p>' + t('web_queue_empty') + '</p>';
                } else {
                    html += '<h3>' + t('web_queue_title') + ' (' + queue.length + ')</h3>';
                    html += '<div>';
                    queue.forEach((item, idx) => {
                        const gameName = item.game_name || 'Unknown';
                        const platform = item.platform || 'N/A';
                        const status = item.status || 'Queued';
                        html += `
                            <div class="info-item" style="display: flex; justify-content: space-between; align-items: center;">
                                <div style="flex: 1;">
                                    <strong>${idx + 1}. 📁 ${gameName}</strong>
                                    <div style="margin-top: 5px; font-size: 0.9em; color: #666;">
                                        Platform: ${platform} | Status: ${status}
                                    </div>
                                </div>
                                <button class="btn-action" onclick='removeFromQueue("${item.task_id.replace(/"/g, "&quot;").replace(/'/g, "&#39;")}", this)' title="${t('web_remove')}">
                                    ❌
                                </button>
                            </div>
                        `;
                    });
                    html += '</div>';
                    
                    // Bouton pour vider la queue
                    html += '<button class="btn-action" onclick="clearQueue()" style="margin-top: 15px; background: #dc3545; color: white; padding: 10px 15px; border: none; border-radius: 5px; cursor: pointer;">';
                    html += t('web_queue_clear') + '</button>';
                }
                
                html += '</div>';
                container.innerHTML = html;
                
            } catch (error) {
                container.innerHTML = `<p style="color:red;">❌ ${t('web_error')}: ${error.message}</p>`;
            }
        }
        
        // Supprimer un élément de la queue
        async function removeFromQueue(taskId, btn) {
            if (!confirm(t('web_confirm_remove_queue'))) {
                return;
            }
            
            try {
                const response = await fetch('/api/queue/remove', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_id: taskId })
                });
                const data = await response.json();
                if (data.success) {
                    btn.style.color = '#28a745';
                    btn.textContent = '✅';
                    setTimeout(() => { loadQueue(); }, 500);
                } else {
                    alert(t('web_error') + ': ' + data.error);
                }
            } catch (error) {
                alert(t('web_error') + ': ' + error.message);
            }
        }
        
        // Vider la queue
        async function clearQueue() {
            if (!confirm(t('web_confirm_clear_queue'))) {
                return;
            }
            
            try {
                const response = await fetch('/api/queue/clear', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const data = await response.json();
                if (data.success) {
                    alert(t('web_queue_cleared'));
                    loadQueue();
                } else {
                    alert(t('web_error') + ': ' + data.error);
                }
            } catch (error) {
                alert(t('web_error') + ': ' + error.message);
            }
        }
        
        // Checker les téléchargements terminés pour afficher les toasts
        async function checkCompletedDownloads() {
            try {
                const response = await fetch('/api/history');
                const data = await response.json();
                
                if (!data.success || !data.history) return;
                
                // Parcourir l'historique récent pour détecter les complétions
                data.history.slice(0, 10).forEach(entry => {
                    const gameKey = `${entry.platform}_${entry.game_name}`;
                    const status = entry.status || '';
                    
                    // Si ce téléchargement n'était pas tracké et il est maintenant complété/erreur/etc
                    if (!trackedDownloads[gameKey]) {
                        if (status === 'Download_OK' || status === 'Completed') {
                            showToast(`✅ "${entry.game_name}" ${t('web_download_success')}`, 'success', 4000);
                            trackedDownloads[gameKey] = 'completed';
                        } else if (status === 'Erreur' || status === 'error') {
                            showToast(`❌ ${t('web_download_error_for')} "${entry.game_name}"`, 'error', 5000);
                            trackedDownloads[gameKey] = 'error';
                        } else if (status === 'Already_Present') {
                            showToast(`ℹ️ "${entry.game_name}" ${t('web_already_present')}`, 'info', 3000);
                            trackedDownloads[gameKey] = 'already_present';
                        } else if (status === 'Canceled') {
                            // Ne pas afficher de toast pour les téléchargements annulés
                            trackedDownloads[gameKey] = 'canceled';
                        }
                    }
                });
                
                // Sauvegarder dans localStorage
                localStorage.setItem('trackedDownloads', JSON.stringify(trackedDownloads));
                
                // Nettoyer les vieux téléchargements (garder seulement les 50 derniers)
                const keys = Object.keys(trackedDownloads);
                if (keys.length > 100) {
                    // Supprimer les 50 plus anciens
                    keys.slice(0, 50).forEach(key => {
                        delete trackedDownloads[key];
                    });
                    localStorage.setItem('trackedDownloads', JSON.stringify(trackedDownloads));
                }
            } catch (error) {
                console.error('[DEBUG] Erreur checkCompletedDownloads:', error);
            }
        }
        
        // Charger l'historique
        async function loadHistory() {
            const container = document.getElementById('history-content');
            container.innerHTML = '<div class="loading">⏳ Chargement...</div>';
            
            try {
                const response = await fetch('/api/history');
                const data = await response.json();
                
                if (!data.success) throw new Error(data.error);
                
                if (data.history.length === 0) {
                    container.innerHTML = '<p>' + t('web_history_empty') + '</p>';
                    return;
                }
                
                // Pré-charger les traductions
                const platformLabel = t('web_history_platform');
                const sizeLabel = t('web_history_size');
                const statusCompleted = t('web_history_status_completed');
                const statusError = t('web_history_status_error');
                const statusCanceled = t('history_status_canceled');
                const statusAlreadyPresent = t('status_already_present');
                const statusQueued = t('download_queued');
                const statusDownloading = t('download_in_progress');
                
                container.innerHTML = data.history.map(h => {
                    const status = h.status || '';
                    const isError = status === 'Erreur' || status === 'error';
                    const isCanceled = status === 'Canceled';
                    const isAlreadyPresent = status === 'Already_Present';
                    const isQueued = status === 'Queued';
                    const isDownloading = status === 'Downloading' || status === 'Connecting' || 
                                         status === 'Extracting' || status.startsWith('Try ');
                    const isSuccess = status === 'Download_OK' || status === 'Completed';
                    
                    // Déterminer l'icône et la couleur
                    let statusIcon = '✅';  // par défaut succès
                    let statusColor = '#28a745';  // vert
                    let statusText = statusCompleted;
                    
                    if (isError) {
                        statusIcon = '❌';
                        statusColor = '#dc3545';  // rouge
                        statusText = statusError;
                    } else if (isCanceled) {
                        statusIcon = '⏸️';
                        statusColor = '#ffc107';  // orange
                        statusText = statusCanceled;
                    } else if (isAlreadyPresent) {
                        statusIcon = 'ℹ️';
                        statusColor = '#17a2b8';  // bleu clair
                        statusText = statusAlreadyPresent;
                    } else if (isQueued) {
                        statusIcon = '📋';
                        statusColor = '#6c757d';  // gris (en attente)
                        statusText = statusQueued;
                    } else if (isDownloading) {
                        statusIcon = '⬇️';
                        statusColor = '#007bff';  // bleu (en cours)
                        statusText = statusDownloading;
                    }
                    
                    const sizeFormatted = h.total_size ? formatSize(h.total_size) : 'N/A';
                    const platform = h.platform || 'N/A';
                    const timestamp = h.timestamp || 'N/A';
                    
                    // Debug: log le timestamp pour vérifier
                    if (!h.timestamp) {
                        console.log('[DEBUG] Timestamp manquant pour:', h.game_name, 'Object:', h);
                    }
                    
                    return `
                        <div class="history-item ${isError ? 'error' : ''}">
                            <div style="display: flex; justify-content: space-between; align-items: start;">
                                <div style="flex: 1;">
                                    <strong>${statusIcon} ${h.game_name || 'Inconnu'}</strong>
                                    <div style="margin-top: 5px; font-size: 0.9em; color: #666;">
                                        📦 ${platformLabel}: ${platform}
                                    </div>
                                    <div style="margin-top: 3px; font-size: 0.85em; color: #666;">
                                        💾 ${sizeLabel}: ${sizeFormatted}
                                    </div>
                                    <div style="margin-top: 3px; font-size: 0.85em; color: #666;">
                                        📅 Date: ${timestamp}
                                    </div>
                                </div>
                                <div style="text-align: right; min-width: 100px;">
                                    <span style="background: ${statusColor}; color: white; padding: 4px 10px; border-radius: 5px; font-size: 0.85em;">
                                        ${statusText}
                                    </span>
                                </div>
                            </div>
                            ${h.message ? `<div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #e0e0e0; font-size: 0.85em; color: #666;">${h.message}</div>` : ''}
                        </div>
                    `;
                }).join('') + `
                    <div style="margin-top: 30px; text-align: center;">
                        <button onclick="clearHistory()" style="background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); color: white; border: none; padding: 12px 30px; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer;">
                            🗑️ ${t('web_history_clear')}
                        </button>
                    </div>
                `;
            } catch (error) {
                container.innerHTML = `<p style="color:red;">${t('web_error')}: ${error.message}</p>`;
            }
        }
        
        // Vider l'historique
        async function clearHistory() {
            if (!confirm(t('web_history_clear') + '?\\n\\nThis action cannot be undone.')) {
                return;
            }
            
            try {
                const response = await fetch('/api/clear-history', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                const data = await response.json();
                
                if (data.success) {
                    alert('✅ ' + t('web_history_cleared'));
                    loadHistory(); // Recharger l\\'historique
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                alert('❌ ' + t('web_error_clear_history', error.message));
            }
        }
        
        // Charger les settings
        async function loadSettings() {
            const container = document.getElementById('settings-content');
            container.innerHTML = '<div class="loading">⏳ Chargement...</div>';
            
            try {
                // Charger les settings et les infos système en parallèle
                const [settingsResponse, systemInfoResponse] = await Promise.all([
                    fetch('/api/settings'),
                    fetch('/api/system_info')
                ]);
                
                const settingsData = await settingsResponse.json();
                const systemInfoData = await systemInfoResponse.json();
                
                if (!settingsData.success) throw new Error(settingsData.error);
                
                const settings = settingsData.settings;
                const info = settingsData.system_info;
                const systemInfo = systemInfoData.success ? systemInfoData.system_info : null;
                
                // Pré-charger les traductions
                const osLabel = t('web_settings_os');
                const platformsCountLabel = t('web_settings_platforms_count');
                const showUnsupportedLabel = t('web_settings_show_unsupported');
                const allowUnknownLabel = t('web_settings_allow_unknown');
                
                // Construire la section d'informations système détaillées (dans un collapse fermé par défaut)
                let systemInfoHTML = '';
                if (systemInfo && (systemInfo.model || systemInfo.cpu_model)) {
                    systemInfoHTML = `
                        <details style="margin-top: 20px; margin-bottom: 20px;">
                            <summary style="cursor: pointer; padding: 12px 15px; background: linear-gradient(135deg, #007bff 0%, #0056b3 100%); color: white; border-radius: 8px; font-weight: bold; font-size: 1.1em; list-style: none; display: flex; align-items: center; gap: 10px;">
                                <span class="collapse-arrow">▶</span>
                                🖥️ ${t('web_system_info_title') || 'System Information'}
                                <span style="margin-left: auto; font-size: 0.85em; opacity: 0.9;">${systemInfo.model || systemInfo.system || ''}</span>
                            </summary>
                            <div class="info-grid" style="margin-top: 10px; background: #f0f8ff; padding: 15px; border-radius: 0 0 8px 8px; border: 2px solid #007bff; border-top: none;">
                                ${systemInfo.model ? `
                                    <div class="info-item">
                                        <strong>💻 Model</strong>
                                        ${systemInfo.model}
                                    </div>
                                ` : ''}
                                ${systemInfo.system ? `
                                    <div class="info-item">
                                        <strong>🐧 System</strong>
                                        ${systemInfo.system}
                                    </div>
                                ` : ''}
                                ${systemInfo.architecture ? `
                                    <div class="info-item">
                                        <strong>⚙️ Architecture</strong>
                                        ${systemInfo.architecture}
                                    </div>
                                ` : ''}
                                ${systemInfo.cpu_model ? `
                                    <div class="info-item">
                                        <strong>🔧 CPU Model</strong>
                                        ${systemInfo.cpu_model}
                                    </div>
                                ` : ''}
                                ${systemInfo.cpu_cores ? `
                                    <div class="info-item">
                                        <strong>🧮 CPU Cores</strong>
                                        ${systemInfo.cpu_cores}
                                    </div>
                                ` : ''}
                                ${systemInfo.cpu_max_frequency ? `
                                    <div class="info-item">
                                        <strong>⚡ CPU Frequency</strong>
                                        ${systemInfo.cpu_max_frequency}
                                    </div>
                                ` : ''}
                                ${systemInfo.cpu_features ? `
                                    <div class="info-item">
                                        <strong>✨ CPU Features</strong>
                                        ${systemInfo.cpu_features}
                                    </div>
                                ` : ''}
                                ${systemInfo.temperature ? `
                                    <div class="info-item">
                                        <strong>🌡️ Temperature</strong>
                                        ${systemInfo.temperature}
                                    </div>
                                ` : ''}
                                ${systemInfo.available_memory && systemInfo.total_memory ? `
                                    <div class="info-item">
                                        <strong>💾 Memory</strong>
                                        ${systemInfo.available_memory} / ${systemInfo.total_memory}
                                    </div>
                                ` : ''}
                                ${systemInfo.display_resolution ? `
                                    <div class="info-item">
                                        <strong>🖥️ Display Resolution</strong>
                                        ${systemInfo.display_resolution}
                                    </div>
                                ` : ''}
                                ${systemInfo.display_refresh_rate ? `
                                    <div class="info-item">
                                        <strong>🔄 Refresh Rate</strong>
                                        ${systemInfo.display_refresh_rate}
                                    </div>
                                ` : ''}
                                ${systemInfo.data_partition_format ? `
                                    <div class="info-item">
                                        <strong>💽 Partition Format</strong>
                                        ${systemInfo.data_partition_format}
                                    </div>
                                ` : ''}
                                ${systemInfo.data_partition_space ? `
                                    <div class="info-item">
                                        <strong>💿 Available Space</strong>
                                        ${systemInfo.data_partition_space}
                                    </div>
                                ` : ''}
                                ${systemInfo.network_ip ? `
                                    <div class="info-item">
                                        <strong>🌐 Network IP</strong>
                                        ${systemInfo.network_ip}
                                    </div>
                                ` : ''}
                                <div class="info-item">
                                    <strong>🎮 ${platformsCountLabel}</strong>
                                    ${info.platforms_count}
                                </div>
                            </div>
                        </details>
                    `;
                }
                
                container.innerHTML = `
                    <h2 data-translate="web_settings_title">ℹ️ ${t('web_settings_title')}</h2>
                    
                    ${systemInfoHTML}
                    
                    <h3 style="margin-top: 30px; margin-bottom: 15px;">RGSX Configuration ⚙️</h3>
                    
                    <div style="margin-bottom: 20px; background: #f0f8ff; padding: 15px; border-radius: 8px; border: 2px solid #007bff;">
                        <label style="display: block; margin-bottom: 10px; font-size: 1.1em;">📁 ${t('web_settings_roms_folder')}</label>
                        <div style="display: flex; gap: 10px; margin-bottom: 8px; flex-wrap: wrap;">
                            <input type="text" id="setting-roms-folder" value="${settings.roms_folder || ''}" 
                                   data-translate-placeholder="web_settings_roms_placeholder"
                                   placeholder="${t('web_settings_roms_placeholder')}"
                                   style="flex: 1; min-width: 200px;">
                            <button onclick="browseRomsFolder()" 
                                    style="background: linear-gradient(135deg, #007bff 0%, #0056b3 100%); color: white; border: none; padding: 10px 20px; border-radius: 5px; font-weight: bold; cursor: pointer; white-space: nowrap; flex-shrink: 0;">
                                📂 ${t('web_settings_browse')}
                            </button>
                        </div>
                        <small style="color: #666; display: block;">
                            Current: <strong>${info.roms_folder}</strong> ${settings.roms_folder ? '(custom)' : '(default)'}
                        </small>
                    </div>
                    
                
                    
                    <div style="background: #f9f9f9; padding: 20px; border-radius: 8px;">
                        <div style="margin-bottom: 20px;">
                            <label>🌍 ${t('web_settings_language')}</label>
                            <select id="setting-language">
                                <option value="en" ${settings.language === 'en' ? 'selected' : ''}>English</option>
                                <option value="fr" ${settings.language === 'fr' ? 'selected' : ''}>Français</option>
                                <option value="es" ${settings.language === 'es' ? 'selected' : ''}>Español</option>
                                <option value="de" ${settings.language === 'de' ? 'selected' : ''}>Deutsch</option>
                                <option value="it" ${settings.language === 'it' ? 'selected' : ''}>Italiano</option>
                                <option value="pt" ${settings.language === 'pt' ? 'selected' : ''}>Português</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label class="checkbox-label">
                                <input type="checkbox" id="setting-music" ${settings.music_enabled ? 'checked' : ''}>
                                <span>🎵 ${t('web_settings_music')}</span>
                            </label>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label>🔤 ${t('web_settings_font_scale')} (${settings.accessibility?.font_scale || 1.0})</label>
                            <input type="range" id="setting-font-scale" min="0.5" max="2.0" step="0.1" 
                                   value="${settings.accessibility?.font_scale || 1.0}"
                                   style="width: 100%;">
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label>📐 ${t('web_settings_grid')}</label>
                            <select id="setting-grid">
                                <option value="3x3" ${settings.display?.grid === '3x3' ? 'selected' : ''}>3x3</option>
                                <option value="3x4" ${settings.display?.grid === '3x4' ? 'selected' : ''}>3x4</option>
                                <option value="4x3" ${settings.display?.grid === '4x3' ? 'selected' : ''}>4x3</option>
                                <option value="4x4" ${settings.display?.grid === '4x4' ? 'selected' : ''}>4x4</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label>🖋️ ${t('web_settings_font_family')}</label>
                            <select id="setting-font-family">
                                <option value="pixel" ${settings.display?.font_family === 'pixel' ? 'selected' : ''}>Pixel</option>
                                <option value="dejavu" ${settings.display?.font_family === 'dejavu' ? 'selected' : ''}>DejaVu</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label class="checkbox-label">
                                <input type="checkbox" id="setting-symlink" ${settings.symlink?.enabled ? 'checked' : ''}>
                                <span>🔗 ${t('web_settings_symlink')}</span>
                            </label>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label>📦 ${t('web_settings_source_mode')}</label>
                            <select id="setting-sources-mode">
                                <option value="rgsx" ${settings.sources?.mode === 'rgsx' ? 'selected' : ''}>RGSX (default)</option>
                                <option value="custom" ${settings.sources?.mode === 'custom' ? 'selected' : ''}>Custom</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label>🔗 ${t('web_settings_custom_url')}</label>
                            <input type="text" id="setting-custom-url" value="${settings.sources?.custom_url || ''}" 
                                   data-translate-placeholder="web_settings_custom_url_placeholder"
                                   placeholder="${t('web_settings_custom_url_placeholder')}">
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label class="checkbox-label">
                                <input type="checkbox" id="setting-auto-extract" ${settings.auto_extract !== false ? 'checked' : ''}>
                                <span>📦 ${t('web_settings_auto_extract')}</span>
                            </label>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label class="checkbox-label">
                                <input type="checkbox" id="setting-show-unsupported" ${settings.show_unsupported_platforms ? 'checked' : ''}>
                                <span>👀 ${showUnsupportedLabel}</span>
                            </label>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label class="checkbox-label">
                                <input type="checkbox" id="setting-allow-unknown" ${settings.allow_unknown_extensions ? 'checked' : ''}>
                                <span>⚠️ ${allowUnknownLabel}</span>
                            </label>
                        </div>
                        
                        ${info.system === 'Linux' ? `
                        <h4 style="margin-top: 25px; margin-bottom: 15px; border-top: 1px solid #ddd; padding-top: 15px;">🐧 Linux/Batocera Options</h4>
                        
                        <div style="margin-bottom: 20px;">
                            <label class="checkbox-label">
                                <input type="checkbox" id="setting-web-service" ${settings.web_service_at_boot ? 'checked' : ''}>
                                <span>🌐 ${t('web_settings_web_service')}</span>
                            </label>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label class="checkbox-label">
                                <input type="checkbox" id="setting-custom-dns" ${settings.custom_dns_at_boot ? 'checked' : ''}>
                                <span>🔒 ${t('web_settings_custom_dns')}</span>
                            </label>
                        </div>
                        ` : ''}
                        
                        <h4 style="margin-top: 25px; margin-bottom: 15px; border-top: 1px solid #ddd; padding-top: 15px;">🔑 API Keys</h4>
                        
                        <div style="margin-bottom: 15px;">
                            <label>1fichier API Key</label>
                            <input type="password" id="setting-api-1fichier" value="${settings.api_keys?.['1fichier'] || ''}" 
                                   placeholder="Enter 1fichier API key">
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <label>AllDebrid API Key</label>
                            <input type="password" id="setting-api-alldebrid" value="${settings.api_keys?.alldebrid || ''}" 
                                   placeholder="Enter AllDebrid API key">
                        </div>

                        <div style="margin-bottom: 15px;">
                            <label>Debrid-Link API Key</label>
                            <input type="password" id="setting-api-debridlink" value="${settings.api_keys?.debridlink || ''}" 
                                   placeholder="Enter Debrid-Link API key">
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label>RealDebrid API Key</label>
                            <input type="password" id="setting-api-realdebrid" value="${settings.api_keys?.realdebrid || ''}" 
                                   placeholder="Enter RealDebrid API key">
                        </div>
                        
                        <button id="save-settings-btn" style="width: 100%; background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; border: none; padding: 15px; border-radius: 8px; font-size: 18px; font-weight: bold; cursor: pointer; margin-top: 10px;">
                            💾 ${t('web_settings_save')}
                        </button>
                    </div>
                `;
                
                // Mettre à jour l'affichage de la valeur du font scale en temps réel
                document.getElementById('setting-font-scale').addEventListener('input', function(e) {
                    const label = e.target.previousElementSibling;
                    label.textContent = `🔤 ${t('web_settings_font_scale')} (${e.target.value})`;
                });
                
                // Attacher l'événement de sauvegarde au bouton
                document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
                
            } catch (error) {
                container.innerHTML = `<p style="color:red;">${t('web_error')}: ${error.message}</p>`;
            }
        }
        
        // Sauvegarder les settings
        async function saveSettings(event) {
            // Désactiver le bouton pendant la sauvegarde
            const saveButton = event?.target;
            const originalText = saveButton?.textContent;
            if (saveButton) {
                saveButton.disabled = true;
                saveButton.textContent = '⏳ Saving...';
            }
            
            try {
                // Collect region filters
                const regionFiltersObj = {};
                regionFilters.forEach((mode, region) => {
                    regionFiltersObj[region] = mode;
                });
                
                const settings = {
                    language: document.getElementById('setting-language').value,
                    music_enabled: document.getElementById('setting-music').checked,
                    accessibility: {
                        font_scale: parseFloat(document.getElementById('setting-font-scale').value)
                    },
                    display: {
                        grid: document.getElementById('setting-grid').value,
                        font_family: document.getElementById('setting-font-family').value
                    },
                    symlink: {
                        enabled: document.getElementById('setting-symlink').checked
                    },
                    sources: {
                        mode: document.getElementById('setting-sources-mode').value,
                        custom_url: document.getElementById('setting-custom-url').value
                    },
                    show_unsupported_platforms: document.getElementById('setting-show-unsupported').checked,
                    allow_unknown_extensions: document.getElementById('setting-allow-unknown').checked,
                    auto_extract: document.getElementById('setting-auto-extract').checked,
                    roms_folder: document.getElementById('setting-roms-folder').value.trim(),
                    // Linux/Batocera options (only if elements exist)
                    web_service_at_boot: document.getElementById('setting-web-service')?.checked || false,
                    custom_dns_at_boot: document.getElementById('setting-custom-dns')?.checked || false,
                    // API Keys
                    api_keys: {
                        '1fichier': document.getElementById('setting-api-1fichier')?.value.trim() || '',
                        'alldebrid': document.getElementById('setting-api-alldebrid')?.value.trim() || '',
                        'debridlink': document.getElementById('setting-api-debridlink')?.value.trim() || '',
                        'realdebrid': document.getElementById('setting-api-realdebrid')?.value.trim() || ''
                    },
                    game_filters: {
                        region_filters: regionFiltersObj,
                        hide_non_release: document.getElementById('hide-non-release')?.checked || savedHideNonRelease,
                        one_rom_per_game: document.getElementById('one-rom-per-game')?.checked || savedOneRomPerGame,
                        regex_mode: document.getElementById('regex-mode')?.checked || savedRegexMode,
                        region_priority: regionPriorityOrder
                    }
                };
                
                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ settings: settings })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    // Réactiver le bouton
                    if (saveButton) {
                        saveButton.disabled = false;
                        saveButton.textContent = originalText;
                    }
                    // Afficher le dialogue de confirmation de redémarrage
                    showRestartDialog();
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                // Réactiver le bouton en cas d'erreur
                if (saveButton) {
                    saveButton.disabled = false;
                    saveButton.textContent = originalText;
                }
                alert('❌ ' + t('web_error_save_settings') + ': ' + error.message);
            }
        }
        
        // Afficher le dialogue de confirmation de redémarrage
        function showRestartDialog() {
            // Créer le dialogue modal
            const modal = document.createElement('div');
            modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 10000;';
            
            const dialog = document.createElement('div');
            dialog.style.cssText = 'background: white; padding: 30px; border-radius: 10px; max-width: 500px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);';
            
            const title = document.createElement('h2');
            title.textContent = t('web_restart_confirm_title');
            title.style.cssText = 'margin: 0 0 20px 0; color: #333;';
            
            const message = document.createElement('p');
            message.textContent = t('web_restart_confirm_message');
            message.style.cssText = 'margin: 0 0 30px 0; color: #666; line-height: 1.5;';
            
            const buttonContainer = document.createElement('div');
            buttonContainer.style.cssText = 'display: flex; gap: 10px; justify-content: flex-end;';
            
            const btnNo = document.createElement('button');
            btnNo.textContent = t('web_restart_no');
            btnNo.style.cssText = 'padding: 10px 20px; background: #6c757d; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px;';
            btnNo.onclick = () => {
                modal.remove();
                alert('✅ ' + t('web_settings_saved'));
            };
            
            const btnYes = document.createElement('button');
            btnYes.textContent = t('web_restart_yes');
            btnYes.style.cssText = 'padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px;';
            btnYes.onclick = async () => {
                modal.remove();
                await restartApplication();
            };
            
            buttonContainer.appendChild(btnNo);
            buttonContainer.appendChild(btnYes);
            
            dialog.appendChild(title);
            dialog.appendChild(message);
            dialog.appendChild(buttonContainer);
            modal.appendChild(dialog);
            document.body.appendChild(modal);
        }
        
        // Redémarrer l'application
        async function restartApplication() {
            try {
                const response = await fetch('/api/restart', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                const data = await response.json();
                
                if (data.success) {
                    alert('✅ ' + t('web_restart_success'));
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                alert('❌ ' + t('web_restart_error', error.message));
            }
        }
        
        // Générer un fichier ZIP de support
        async function generateSupportZip(event) {
            try {
                // Afficher un message de chargement
                const loadingMsg = t('web_support_generating');
                const originalButton = event ? event.target : null;
                if (originalButton) {
                    originalButton.disabled = true;
                    originalButton.innerHTML = '⏳ ' + loadingMsg;
                }
                
                // Appeler l'API pour générer le ZIP
                const response = await fetch('/api/support', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.error || t('web_error_unknown'));
                }
                
                // Télécharger le fichier
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                
                // Extraire le nom du fichier depuis les headers
                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'rgsx_support.zip';
                if (contentDisposition) {
                    const matches = /filename="?([^"]+)"?/.exec(contentDisposition);
                    if (matches && matches[1]) {
                        filename = matches[1];
                    }
                }
                
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                // Afficher le message d'instructions dans une modal
                showSupportModal(t('web_support_title'), t('web_support_message'));
                
                // Restaurer le bouton
                if (originalButton) {
                    originalButton.disabled = false;
                    originalButton.innerHTML = '🆘 ' + t('web_support');
                }
                
            } catch (error) {
                console.error('Erreur génération support:', error);
                alert('❌ ' + t('web_support_error', error.message));
                
                // Restaurer le bouton en cas d'erreur
                const originalButton = event ? event.target : null;
                if (originalButton) {
                    originalButton.disabled = false;
                    originalButton.innerHTML = '🆘 ' + t('web_support');
                }
            }
        }
        
        // Navigateur de répertoires pour ROMs folder
        let currentBrowsePath = '';
        let browseInitialized = false;
        
        async function browseRomsFolder() {
            try {
                // Récupérer le chemin actuel de l'input SEULEMENT au premier appel
                if (!browseInitialized) {
                    const inputValue = document.getElementById('setting-roms-folder').value.trim();
                    if (inputValue) {
                        currentBrowsePath = inputValue;
                    }
                    browseInitialized = true;
                }
                
                const response = await fetch(`/api/browse-directories?path=${encodeURIComponent(currentBrowsePath)}`);
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error(data.error || 'Erreur lors du listage des répertoires');
                }
                
                // Créer une modal pour afficher les répertoires
                const modal = document.createElement('div');
                modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 9999; display: flex; align-items: center; justify-content: center; padding: 20px;';
                
                const content = document.createElement('div');
                content.style.cssText = 'background: white; border-radius: 10px; padding: 20px; max-width: 600px; width: 100%; max-height: 80vh; overflow-y: auto;';
                
                // Titre avec chemin actuel
                const title = document.createElement('h2');
                title.textContent = '📂 ' + t('web_browse_title');
                title.style.marginBottom = '10px';
                content.appendChild(title);
                
                const pathDisplay = document.createElement('div');
                pathDisplay.style.cssText = 'background: #f0f0f0; padding: 10px; border-radius: 5px; margin-bottom: 15px; word-break: break-all; font-family: monospace; font-size: 14px;';
                pathDisplay.textContent = data.current_path || t('web_browse_select_drive');
                content.appendChild(pathDisplay);
                
                // Boutons d'action
                const buttonContainer = document.createElement('div');
                buttonContainer.style.cssText = 'display: flex; gap: 10px; justify-content: flex-end;';
                
                // Bouton parent - afficher si parent_path n'est pas null (même si c'est une chaîne vide pour revenir aux lecteurs)
                if (data.parent_path !== null && data.parent_path !== undefined) {
                    const parentBtn = document.createElement('button');
                    parentBtn.textContent = data.parent_path === '' ? '💾 ' + t('web_browse_drives') : '⬆️ ' + t('web_browse_parent');
                    parentBtn.style.cssText = 'flex: 1; padding: 10px; background: #6c757d; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;';
                    parentBtn.onclick = () => {
                        currentBrowsePath = data.parent_path;
                        modal.remove();
                        browseRomsFolder();
                    };
                    buttonContainer.appendChild(parentBtn);
                }
                
                // Bouton sélectionner ce dossier
                if (data.current_path) {
                    const selectBtn = document.createElement('button');
                    selectBtn.textContent = '✅ ' + t('web_browse_select');
                    selectBtn.style.cssText = 'flex: 2; padding: 10px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;';
                    selectBtn.onclick = () => {
                        document.getElementById('setting-roms-folder').value = data.current_path;
                        currentBrowsePath = '';
                        browseInitialized = false;
                        modal.remove();
                        
                        // Afficher une alerte informant qu'il faut redémarrer
                        alert('⚠️ ' + t('web_browse_alert_restart', data.current_path));
                    };
                    buttonContainer.appendChild(selectBtn);
                }
                
                // Bouton annuler
                const cancelBtn = document.createElement('button');
                cancelBtn.textContent = '❌ ' + t('web_browse_cancel');
                cancelBtn.style.cssText = 'flex: 1; padding: 10px; background: #dc3545; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;';
                cancelBtn.onclick = () => {
                    currentBrowsePath = '';
                    browseInitialized = false;
                    modal.remove();
                };
                buttonContainer.appendChild(cancelBtn);
                
                content.appendChild(buttonContainer);
                
                // Liste des répertoires
                const dirList = document.createElement('div');
                dirList.style.cssText = 'max-height: 400px; overflow-y: auto; border: 2px solid #ddd; border-radius: 5px;';
                
                if (data.directories.length === 0) {
                    const emptyMsg = document.createElement('div');
                    emptyMsg.style.cssText = 'padding: 20px; text-align: center; color: #666;';
                    emptyMsg.textContent = t('web_browse_empty');
                    dirList.appendChild(emptyMsg);
                } else {
                    data.directories.forEach(dir => {
                        const dirItem = document.createElement('div');
                        dirItem.style.cssText = 'padding: 12px; border-bottom: 1px solid #eee; cursor: pointer; display: flex; align-items: center; gap: 10px; transition: background 0.2s;';
                        dirItem.onmouseover = () => dirItem.style.background = '#f0f0f0';
                        dirItem.onmouseout = () => dirItem.style.background = 'white';
                        
                        const icon = document.createElement('span');
                        icon.textContent = dir.is_drive ? '💾' : '📁';
                        icon.style.fontSize = '20px';
                        
                        const name = document.createElement('span');
                        name.textContent = dir.name;
                        name.style.flex = '1';
                        
                        dirItem.appendChild(icon);
                        dirItem.appendChild(name);
                        
                        dirItem.onclick = () => {
                            currentBrowsePath = dir.path;
                            modal.remove();
                            browseRomsFolder();
                        };
                        
                        dirList.appendChild(dirItem);
                    });
                }
                
                content.appendChild(dirList);
                modal.appendChild(content);
                document.body.appendChild(modal);
                
                // Fermer avec clic en dehors
                modal.onclick = (e) => {
                    if (e.target === modal) {
                        currentBrowsePath = '';
                        browseInitialized = false;
                        modal.remove();
                    }
                };
                
            } catch (error) {
                alert('❌ ' + t('web_error_browse', error.message));
            }
        }
        
        // Initialisation au démarrage
        async function init() {
            await loadTranslations();  // Charger les traductions
            applyTranslations();         // Appliquer les traductions à l'interface
            loadPlatforms();            // Charger les plateformes
            updateRegionPriorityDisplay(); // Update initial display
            
            // Vérifier les téléchargements complétés toutes les 2 secondes
            setInterval(checkCompletedDownloads, 2000);
        }
        
        // Lancer l'initialisation
        init();
    