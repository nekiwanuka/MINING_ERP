(function () {
    function translatePage() {
        var script = document.getElementById('ui-translations');
        if (!script) { return; }
        var translations = JSON.parse(script.textContent || '{}');
        var skipTags = { SCRIPT: true, STYLE: true, TEXTAREA: true };
        var phraseKeys = Object.keys(translations).sort(function (left, right) {
            return right.length - left.length;
        });

        function escapeRegExp(value) {
            return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        }

        function translateValue(value) {
            var trimmed = String(value || '').replace(/\s+/g, ' ').trim();
            if (!trimmed) { return null; }
            return translations[trimmed] || null;
        }

        function translateMixedText(value) {
            var translated = String(value || '');
            phraseKeys.forEach(function (key) {
                if (key.trim().length < 2 || translated.toLowerCase().indexOf(key.toLowerCase()) === -1) { return; }
                if (/^[A-Za-z][A-Za-z0-9 /().,-]*$/.test(key)) {
                    translated = translated.replace(
                        new RegExp('(^|[^A-Za-z0-9])(' + escapeRegExp(key) + ')(?=$|[^A-Za-z0-9])', 'gi'),
                        function (match, prefix) { return prefix + translations[key]; }
                    );
                } else {
                    translated = translated.replace(new RegExp(escapeRegExp(key), 'gi'), translations[key]);
                }
            });
            return translated === value ? null : translated;
        }

        function translateTextNodes(root) {
            var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            var nodes = [];
            while (walker.nextNode()) { nodes.push(walker.currentNode); }
            nodes.forEach(function (node) {
                if (!node.parentElement || skipTags[node.parentElement.tagName]) { return; }
                if (node.parentElement.closest('.language-form, .login-language-form')) { return; }
                var translated = translateValue(node.nodeValue);
                if (translated) {
                    node.nodeValue = node.nodeValue.replace(/\S(?:.|\n)*\S|\S/, translated);
                    return;
                }
                translated = translateMixedText(node.nodeValue);
                if (translated) { node.nodeValue = translated; }
            });
        }

        function translateAttributes(root) {
            root.querySelectorAll('[placeholder], [title], [aria-label], input[type="submit"]').forEach(function (element) {
                ['placeholder', 'title', 'aria-label', 'value'].forEach(function (attribute) {
                    if (!element.hasAttribute(attribute)) { return; }
                    var translated = translateValue(element.getAttribute(attribute));
                    if (translated) { element.setAttribute(attribute, translated); }
                });
            });
        }

        translateTextNodes(document.body);
        translateAttributes(document.body);
    }

    function setupMobileMenu() {
        var menuToggle = document.querySelector('.mobile-menu-toggle');
        var menuDrawer = document.getElementById('mobile-menu');
        var menuBackdrop = document.querySelector('.mobile-menu-backdrop');
        var menuCloseControls = document.querySelectorAll('[data-mobile-menu-close]');

        function setMenuOpen(isOpen) {
            if (!menuToggle || !menuDrawer || !menuBackdrop) { return; }
            document.body.classList.toggle('mobile-menu-open', isOpen);
            menuToggle.setAttribute('aria-expanded', String(isOpen));
            menuBackdrop.hidden = !isOpen;
            if (isOpen) {
                var firstControl = menuDrawer.querySelector('a, button, summary, select');
                if (firstControl) { firstControl.focus(); }
            } else {
                menuToggle.focus();
            }
        }

        if (!menuToggle || !menuDrawer || !menuBackdrop) { return; }
        menuToggle.addEventListener('click', function () {
            setMenuOpen(!document.body.classList.contains('mobile-menu-open'));
        });
        menuCloseControls.forEach(function (control) {
            control.addEventListener('click', function () { setMenuOpen(false); });
        });
        menuDrawer.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () { setMenuOpen(false); });
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') { setMenuOpen(false); }
        });
    }

    function setupToasts() {
        document.querySelectorAll('[data-toast-close]').forEach(function (button) {
            button.addEventListener('click', function () {
                var toast = button.closest('[data-toast]');
                if (toast) { toast.hidden = true; }
            });
        });
    }

    function announce(message) {
        var liveRegion = document.querySelector('[data-app-live-region]');
        if (liveRegion) { liveRegion.textContent = message; }
    }

    function setGlobalLoading(isLoading, message) {
        var overlay = document.querySelector('[data-page-loading-overlay]');
        var progress = document.querySelector('[data-global-progress]');
        if (progress) { progress.classList.toggle('is-active', isLoading); }
        if (!overlay) { return; }
        window.clearTimeout(window.__globalLoadingOverlayTimer);
        if (isLoading) {
            window.__globalLoadingOverlayTimer = window.setTimeout(function () {
                overlay.hidden = false;
                overlay.setAttribute('aria-hidden', 'false');
            }, 450);
        } else {
            overlay.hidden = true;
            overlay.setAttribute('aria-hidden', 'true');
        }
        if (message) {
            var label = overlay.querySelector('strong');
            if (label) { label.textContent = message; }
            announce(message);
        }
    }

    function shouldShowNavigationLoading(link) {
        if (!link || link.target || link.hasAttribute('download') || link.hasAttribute('data-dialog-target') || link.hasAttribute('data-confirm-action')) { return false; }
        if (link.origin !== window.location.origin) { return false; }
        if (link.hash && link.pathname === window.location.pathname && link.search === window.location.search) { return false; }
        if (/\/(download|uploaded-document)\/?$/i.test(link.pathname)) { return false; }
        return !/\.(csv|pdf|txt|docx?|xlsx?|png|jpe?g|gif|webp|zip)$/i.test(link.pathname);
    }

    function showTemporaryLoading(message) {
        setGlobalLoading(true, message);
        window.clearTimeout(window.__globalLoadingTimer);
        window.__globalLoadingTimer = window.setTimeout(function () {
            if (document.visibilityState === 'visible') { setGlobalLoading(false); }
        }, 4500);
    }

    function setupConfirmations() {
        var dialog = document.querySelector('[data-confirm-dialog]');
        var dialogMessage = dialog ? dialog.querySelector('[data-confirm-dialog-message]') : null;

        function nativeOrDialogConfirm(control, message, onConfirm) {
            if (!dialog || !dialogMessage || typeof dialog.showModal !== 'function') {
                if (window.confirm(message)) { onConfirm(); }
                return;
            }
            dialogMessage.textContent = message;
            dialog.returnValue = '';
            dialog.showModal();
            dialog.addEventListener('close', function handleClose() {
                dialog.removeEventListener('close', handleClose);
                if (dialog.returnValue === 'confirm') { onConfirm(); }
                else { control.focus(); }
            });
        }

        document.querySelectorAll('[data-confirm-action]').forEach(function (control) {
            control.addEventListener('click', function (event) {
                var message = control.getAttribute('data-confirm-message') || 'Please confirm this action before continuing.';
                var expected = control.getAttribute('data-confirm-value');
                if (expected) {
                    if (window.prompt(message) !== expected) { event.preventDefault(); }
                    return;
                }
                event.preventDefault();
                nativeOrDialogConfirm(control, message, function () {
                    if (control.tagName === 'A') {
                        window.location.assign(control.href);
                    } else if (control.form) {
                        control.form.requestSubmit(control);
                    } else {
                        control.click();
                    }
                });
            });
        });
    }

    function openDialog(targetId) {
        var dialog = document.getElementById(targetId);
        if (!dialog) { return; }
        if (typeof dialog.showModal === 'function') {
            dialog.showModal();
        } else {
            dialog.setAttribute('open', 'open');
        }
    }

    function isInteractiveClick(event) {
        return Boolean(event.target.closest('a, button, input, select, textarea, label'));
    }

    function setupDialogs() {
        document.querySelectorAll('[data-dialog-target]').forEach(function (button) {
            button.addEventListener('click', function () { openDialog(button.getAttribute('data-dialog-target')); });
        });

        document.querySelectorAll('[data-dialog-row]').forEach(function (row) {
            row.addEventListener('click', function (event) {
                if (isInteractiveClick(event)) { return; }
                openDialog(row.getAttribute('data-dialog-row'));
            });
            row.addEventListener('keydown', function (event) {
                if (event.key !== 'Enter' && event.key !== ' ') { return; }
                if (isInteractiveClick(event)) { return; }
                event.preventDefault();
                openDialog(row.getAttribute('data-dialog-row'));
            });
        });

        document.querySelectorAll('.entry-modal').forEach(function (dialog) {
            dialog.querySelectorAll('[data-dialog-close]').forEach(function (button) {
                button.addEventListener('click', function () { dialog.close(); });
            });
            dialog.addEventListener('click', function (event) {
                if (event.target === dialog) { dialog.close(); }
            });
        });
    }

    function setupFuelRefillCalculator() {
        var fuelBeforeInput = document.querySelector('[data-fuel-before-refill]');
        var fuelAfterInput = document.querySelector('[data-fuel-after-refill]');
        var litresIssuedInput = document.querySelector('[data-fuel-litres-issued]');

        function calculateFuelRefillLitres() {
            if (!fuelBeforeInput || !fuelAfterInput || !litresIssuedInput) { return; }
            var beforeValue = Number.parseFloat(fuelBeforeInput.value || '0');
            var afterValue = Number.parseFloat(fuelAfterInput.value || '0');
            if (Number.isNaN(beforeValue) || Number.isNaN(afterValue) || afterValue < beforeValue) {
                litresIssuedInput.value = '';
                return;
            }
            litresIssuedInput.value = (afterValue - beforeValue).toFixed(3);
        }

        if (fuelBeforeInput) { fuelBeforeInput.addEventListener('input', calculateFuelRefillLitres); }
        if (fuelAfterInput) { fuelAfterInput.addEventListener('input', calculateFuelRefillLitres); }
        calculateFuelRefillLitres();
    }

    function setupRequisitionItemForms() {
        var itemList = document.querySelector('[data-item-form-list]');
        var addItemButton = document.querySelector('#add-item-button');
        var totalForms = document.querySelector('#id_items-TOTAL_FORMS');
        var itemTemplate = document.querySelector('#empty-item-template');

        document.querySelectorAll('.item-accordion').forEach(function (item, index) {
            var textarea = item.querySelector('textarea');
            var numberInput = item.querySelector('input[type="number"]');
            var hasValue = (textarea && textarea.value) || (numberInput && numberInput.value);
            item.hidden = index > 0 && !hasValue;
        });

        if (!itemList || !addItemButton || !totalForms || !itemTemplate) { return; }
        addItemButton.addEventListener('click', function () {
            var hiddenItem = itemList.querySelector('.item-accordion[hidden]');
            if (hiddenItem) {
                hiddenItem.hidden = false;
                var firstHiddenControl = hiddenItem.querySelector('textarea, input, select');
                if (firstHiddenControl) { firstHiddenControl.focus(); }
                return;
            }

            var nextIndex = Number.parseInt(totalForms.value, 10);
            var nextNumber = nextIndex + 1;
            var markup = itemTemplate.innerHTML
                .replaceAll('__prefix__', nextIndex)
                .replaceAll('__number__', nextNumber);
            itemList.insertAdjacentHTML('beforeend', markup);
            totalForms.value = nextNumber;
            var firstNewControl = itemList.lastElementChild.querySelector('textarea, input, select');
            if (firstNewControl) { firstNewControl.focus(); }
        });
    }

    function setupTransportTableFilter() {
        var transportFilter = document.querySelector('[data-transport-table-filter]');
        var transportRows = Array.from(document.querySelectorAll('[data-transport-table] tbody tr[data-filter-text]'));
        if (!transportFilter || !transportRows.length) { return; }
        transportFilter.addEventListener('input', function () {
            var query = transportFilter.value.trim().toLowerCase();
            transportRows.forEach(function (row) {
                row.hidden = Boolean(query) && row.dataset.filterText.toLowerCase().indexOf(query) === -1;
            });
        });
    }

    function cellValue(cell) {
        return (cell ? cell.textContent : '').replace(/\s+/g, ' ').trim();
    }

    function compareCells(left, right, index, direction) {
        var leftValue = cellValue(left.children[index]);
        var rightValue = cellValue(right.children[index]);
        var leftNumber = Number(leftValue.replace(/[^0-9.-]/g, ''));
        var rightNumber = Number(rightValue.replace(/[^0-9.-]/g, ''));
        if (!Number.isNaN(leftNumber) && !Number.isNaN(rightNumber) && leftValue.match(/\d/) && rightValue.match(/\d/)) {
            return (leftNumber - rightNumber) * direction;
        }
        return leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: 'base' }) * direction;
    }

    function downloadCsv(filename, rows) {
        var csv = rows.map(function (row) {
            return row.map(function (value) { return '"' + String(value).replaceAll('"', '""') + '"'; }).join(',');
        }).join('\n');
        var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        var link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        link.click();
        URL.revokeObjectURL(link.href);
    }

    function setupDataTables() {
        document.querySelectorAll('.table-wrap table, table.data-table, table.command-table').forEach(function (table, tableIndex) {
            if (table.dataset.tableEnhanced === 'true' || table.closest('.printable-po, .transport-invoice-document, .transport-delivery-note-document')) { return; }
            var headRow = table.tHead ? table.tHead.rows[0] : null;
            var body = table.tBodies[0];
            var rows = body ? Array.from(body.rows).filter(function (row) { return !row.querySelector('.empty-cell'); }) : [];
            if (!headRow || !body || !rows.length) { return; }

            table.dataset.tableEnhanced = 'true';
            table.classList.add('enhanced-table');
            var tableId = table.id || 'enhanced-table-' + tableIndex;
            table.id = tableId;
            var headers = Array.from(headRow.cells).map(function (cell) { return cell.textContent.replace(/\s+/g, ' ').trim(); });

            rows.forEach(function (row) {
                row.dataset.tableText = row.textContent.replace(/\s+/g, ' ').trim().toLowerCase();
                row.dataset.tableMatched = 'true';
                Array.from(row.cells).forEach(function (cell, index) {
                    if (!cell.hasAttribute('data-label') && headers[index]) { cell.setAttribute('data-label', headers[index]); }
                    if (headers[index] && headers[index].toLowerCase() === 'status' && !cell.querySelector('.status-pill, .status-badge, .urgent-pill')) {
                        cell.innerHTML = '<span class="status-pill">' + cell.textContent.replace(/\s+/g, ' ').trim() + '</span>';
                    }
                });
                row.querySelectorAll('a, button').forEach(function (action) {
                    if (action.getAttribute('aria-label')) { return; }
                    var rowName = cellValue(row.cells[0]);
                    var actionText = action.textContent.replace(/\s+/g, ' ').trim() || action.title || 'Open action';
                    action.setAttribute('aria-label', rowName ? actionText + ' for ' + rowName : actionText);
                });
            });

            var selectionHeader = document.createElement('th');
            selectionHeader.scope = 'col';
            selectionHeader.className = 'selection-cell';
            selectionHeader.innerHTML = '<input type="checkbox" aria-label="Select all rows in this table">';
            headRow.insertBefore(selectionHeader, headRow.firstElementChild);
            rows.forEach(function (row) {
                var cell = document.createElement('td');
                cell.className = 'selection-cell';
                cell.setAttribute('data-label', 'Select');
                cell.innerHTML = '<input type="checkbox" aria-label="Select row">';
                row.insertBefore(cell, row.firstElementChild);
            });
            headers.unshift('Select');

            Array.from(headRow.cells).forEach(function (header, index) {
                if (index === 0 || header.querySelector('a, button, input')) { return; }
                var button = document.createElement('button');
                button.type = 'button';
                button.className = 'table-sort-button';
                button.textContent = header.textContent.replace(/\s+/g, ' ').trim();
                button.setAttribute('aria-label', 'Sort by ' + button.textContent);
                button.setAttribute('aria-sort', 'none');
                header.textContent = '';
                header.appendChild(button);
                button.addEventListener('click', function () {
                    var direction = button.dataset.sortDirection === 'asc' ? -1 : 1;
                    Array.from(headRow.querySelectorAll('.table-sort-button')).forEach(function (other) {
                        other.dataset.sortDirection = '';
                        other.setAttribute('aria-sort', 'none');
                    });
                    button.dataset.sortDirection = direction === 1 ? 'asc' : 'desc';
                    button.setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');
                    rows.sort(function (left, right) { return compareCells(left, right, index, direction); }).forEach(function (row) { body.appendChild(row); });
                    currentPage = 1;
                    renderRows();
                });
            });

            var toolbar = document.createElement('div');
            toolbar.className = 'table-toolbar';
            toolbar.innerHTML = '<label class="table-search-field"><span>Search table</span><input type="search" aria-controls="' + tableId + '" placeholder="Search visible rows"></label><div class="table-toolbar-actions"><span class="table-selection-count" aria-live="polite">0 selected</span><button class="secondary-button table-export-button" type="button">Export CSV</button></div>';
            table.parentElement.insertBefore(toolbar, table);

            var searchInput = toolbar.querySelector('input');
            var selectionCount = toolbar.querySelector('.table-selection-count');
            var selectAll = selectionHeader.querySelector('input');
            var rowCheckboxes = rows.map(function (row) { return row.querySelector('.selection-cell input'); });
            var emptyRow = document.createElement('tr');
            emptyRow.className = 'table-client-empty';
            emptyRow.hidden = true;
            emptyRow.innerHTML = '<td colspan="' + headers.length + '"><span class="empty-state"><strong>No rows match this table search.</strong><span>Clear the table search or adjust the page filters.</span></span></td>';
            body.appendChild(emptyRow);
            var pageSize = 10;
            var currentPage = 1;
            var pager = null;
            if (rows.length > pageSize) {
                pager = document.createElement('div');
                pager.className = 'table-pagination';
                pager.innerHTML = '<button class="secondary-button" type="button" data-table-page="prev">Back</button><span aria-live="polite"></span><button class="secondary-button" type="button" data-table-page="next">Next</button>';
                table.parentElement.appendChild(pager);
            }

            function matchedRows() {
                return rows.filter(function (row) { return row.dataset.tableMatched === 'true'; });
            }

            function updateSelection() {
                var visible = rows.filter(function (row) { return !row.hidden; });
                var selected = visible.filter(function (row) { return row.querySelector('.selection-cell input').checked; }).length;
                selectionCount.textContent = selected + ' selected';
                selectAll.checked = visible.length > 0 && selected === visible.length;
                selectAll.indeterminate = selected > 0 && selected < visible.length;
            }

            function renderRows() {
                var matched = matchedRows();
                var pageCount = Math.max(1, Math.ceil(matched.length / pageSize));
                currentPage = Math.max(1, Math.min(currentPage, pageCount));
                var start = (currentPage - 1) * pageSize;
                var end = start + pageSize;
                rows.forEach(function (row) {
                    var matchedIndex = matched.indexOf(row);
                    row.hidden = matchedIndex === -1 || (pager && (matchedIndex < start || matchedIndex >= end));
                });
                emptyRow.hidden = matched.length !== 0;
                if (pager) {
                    pager.querySelector('[data-table-page="prev"]').disabled = currentPage === 1;
                    pager.querySelector('[data-table-page="next"]').disabled = currentPage === pageCount;
                    pager.querySelector('span').textContent = 'Page ' + currentPage + ' of ' + pageCount + ' · ' + matched.length + ' rows';
                    pager.hidden = matched.length <= pageSize;
                }
                updateSelection();
            }

            function applySearch() {
                var query = searchInput.value.trim().toLowerCase();
                rows.forEach(function (row) { row.dataset.tableMatched = String(!query || row.dataset.tableText.indexOf(query) !== -1); });
                currentPage = 1;
                renderRows();
            }

            searchInput.addEventListener('input', applySearch);
            selectAll.addEventListener('change', function () {
                rows.filter(function (row) { return !row.hidden; }).forEach(function (row) { row.querySelector('.selection-cell input').checked = selectAll.checked; });
                updateSelection();
            });
            rowCheckboxes.forEach(function (checkbox) { checkbox.addEventListener('change', updateSelection); });
            if (pager) {
                pager.addEventListener('click', function (event) {
                    var button = event.target.closest('[data-table-page]');
                    if (!button) { return; }
                    currentPage += button.dataset.tablePage === 'next' ? 1 : -1;
                    renderRows();
                });
            }
            toolbar.querySelector('.table-export-button').addEventListener('click', function () {
                var exportRows = [headers.slice(1)].concat(matchedRows().map(function (row) {
                    return Array.from(row.cells).slice(1).map(cellValue);
                }));
                downloadCsv((table.caption ? cellValue(table.caption) : 'table-export') + '.csv', exportRows);
            });
            renderRows();
        });
    }

    function setupTableLoadingStates() {
        document.querySelectorAll('.list-filter-form, .search-form, .procurement-search-form, .requisition-search-form').forEach(function (form) {
            form.addEventListener('submit', function () {
                var panel = form.closest('.panel') || form.parentElement;
                var tablePanel = panel ? panel.nextElementSibling : null;
                if (tablePanel && tablePanel.querySelector('.table-wrap')) { tablePanel.classList.add('table-loading'); }
            });
        });
    }

    function setupKeyboardShortcuts() {
        document.addEventListener('keydown', function (event) {
            if (event.target.closest('input, select, textarea')) { return; }
            if (event.key === '/') {
                var search = document.querySelector('input[type="search"]');
                if (search) {
                    event.preventDefault();
                    search.focus();
                    announce('Search focused');
                }
            }
            if (event.key.toLowerCase() === 'n') {
                var createLink = document.querySelector('.action-create, a[href$="/new/"]');
                if (createLink) {
                    event.preventDefault();
                    createLink.focus();
                    announce('Create action focused');
                }
            }
            if (event.key === '?') {
                announce('Keyboard shortcuts: slash focuses search, N focuses the first create action, Escape closes dialogs and menus.');
            }
        });
    }

    function setupNavigationFeedback() {
        document.addEventListener('click', function (event) {
            var link = event.target.closest('a[href]');
            if (event.defaultPrevented || !shouldShowNavigationLoading(link)) { return; }
            showTemporaryLoading('Loading');
        });
        document.querySelectorAll('form').forEach(function (form) {
            form.addEventListener('submit', function (event) {
                if (event.defaultPrevented || form.method === 'dialog' || form.target || !form.checkValidity()) { return; }
                showTemporaryLoading((form.getAttribute('method') || 'get').toLowerCase() === 'get' ? 'Loading results' : 'Saving');
            });
        });
        window.addEventListener('pageshow', function () { setGlobalLoading(false); });
        window.addEventListener('pagehide', function () { setGlobalLoading(false); });
    }

    function setupFocusManagement() {
        var main = document.getElementById('main-content');
        if (main) { main.focus({ preventScroll: true }); }
        document.querySelectorAll('.toast, .alert-error').forEach(function (notice) {
            if (!notice.hasAttribute('tabindex')) { notice.setAttribute('tabindex', '-1'); }
        });
        var firstError = document.querySelector('.field-invalid input, .field-invalid select, .field-invalid textarea, .alert-error');
        if (firstError) { firstError.focus({ preventScroll: false }); }
    }

    function loadingLabelFor(button, form) {
        var explicitLabel = button.getAttribute('data-loading-label');
        if (explicitLabel) { return explicitLabel; }
        var text = button.textContent.trim().toLowerCase();
        var method = (form.getAttribute('method') || 'get').toLowerCase();
        if (text.indexOf('search') !== -1 || text.indexOf('filter') !== -1 || method === 'get') { return 'Searching...'; }
        if (text.indexOf('sign out') !== -1) { return 'Signing out...'; }
        if (text.indexOf('delete') !== -1 || text.indexOf('remove') !== -1) { return 'Removing...'; }
        return 'Saving...';
    }

    function setupAccessibleFormFields() {
        document.querySelectorAll('.field-block').forEach(function (fieldBlock) {
            var control = fieldBlock.querySelector('input:not([type="hidden"]), select, textarea');
            var helper = fieldBlock.querySelector('.field-helper');
            if (!control) { return; }

            if (fieldBlock.classList.contains('field-required')) {
                control.setAttribute('aria-required', 'true');
            }
            if (fieldBlock.classList.contains('field-invalid')) {
                control.setAttribute('aria-invalid', 'true');
            }
            if (helper && helper.id) {
                var describedBy = (control.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
                if (describedBy.indexOf(helper.id) === -1) { describedBy.push(helper.id); }
                control.setAttribute('aria-describedby', describedBy.join(' '));
            }
        });
    }

    function setupFormSteppers() {
        document.querySelectorAll('[data-form-steps]').forEach(function (stepper) {
            var form = stepper.closest('form');
            var steps = Array.from(stepper.querySelectorAll('[data-form-step]'));
            var dots = Array.from(stepper.querySelectorAll('[data-form-step-dot]'));
            var submitActions = form ? form.querySelector('.form-submit-actions, .transport-save-bar') : null;
            if (!steps.length) { return; }

            var initialIndex = steps.findIndex(function (step) { return step.querySelector('.field-invalid'); });
            var currentIndex = initialIndex >= 0 ? initialIndex : 0;

            function focusStep(index) {
                var firstControl = steps[index].querySelector('input:not([type="hidden"]):not(:disabled), select:not(:disabled), textarea:not(:disabled), button:not(:disabled)');
                if (firstControl) { firstControl.focus({ preventScroll: true }); }
            }

            function controlsForStep(step) {
                return Array.from(step.querySelectorAll('input:not([type="hidden"]), select, textarea')).filter(function (control) {
                    return !control.disabled;
                });
            }

            function stepIsValid(step) {
                var invalidControl = controlsForStep(step).find(function (control) { return !control.checkValidity(); });
                if (!invalidControl) { return true; }
                invalidControl.reportValidity();
                invalidControl.focus({ preventScroll: false });
                return false;
            }

            function showStep(index, shouldFocus) {
                currentIndex = Math.max(0, Math.min(index, steps.length - 1));
                steps.forEach(function (step, stepIndex) {
                    var isActive = stepIndex === currentIndex;
                    step.hidden = !isActive;
                    step.setAttribute('aria-hidden', String(!isActive));
                });
                dots.forEach(function (dot, dotIndex) {
                    dot.classList.toggle('is-active', dotIndex === currentIndex);
                    dot.classList.toggle('is-complete', dotIndex < currentIndex);
                });
                if (submitActions) { submitActions.hidden = currentIndex !== steps.length - 1; }
                if (shouldFocus) { focusStep(currentIndex); }
            }

            stepper.querySelectorAll('[data-form-step-next]').forEach(function (button) {
                button.addEventListener('click', function () {
                    if (stepIsValid(steps[currentIndex])) { showStep(currentIndex + 1, true); }
                });
            });
            stepper.querySelectorAll('[data-form-step-back]').forEach(function (button) {
                button.addEventListener('click', function () { showStep(currentIndex - 1, true); });
            });

            if (form) {
                form.addEventListener('invalid', function (event) {
                    var invalidStep = event.target.closest('[data-form-step]');
                    var invalidIndex = steps.indexOf(invalidStep);
                    if (invalidIndex >= 0 && invalidIndex !== currentIndex) { showStep(invalidIndex, false); }
                }, true);
            }

            showStep(currentIndex, false);
        });
    }

    function resetStandardForms() {
        document.querySelectorAll('form.is-submitting').forEach(function (form) {
            form.dataset.submitting = 'false';
            form.removeAttribute('aria-busy');
            form.classList.remove('is-submitting');
            form.querySelectorAll('.is-loading').forEach(function (button) {
                if (button.dataset.originalLabel) { button.textContent = button.dataset.originalLabel; }
                button.classList.remove('is-loading');
                button.removeAttribute('aria-busy');
                button.disabled = false;
            });
        });
    }

    function setupStandardForms() {
        document.querySelectorAll('form').forEach(function (form) {
            form.addEventListener('submit', function (event) {
                if (event.defaultPrevented || form.dataset.submitting === 'true') { return; }
                var submitter = event.submitter || form.querySelector('button[type="submit"], input[type="submit"]');
                form.dataset.submitting = 'true';
                form.setAttribute('aria-busy', 'true');
                form.classList.add('is-submitting');
                if (!submitter) { return; }
                submitter.dataset.originalLabel = submitter.textContent;
                submitter.textContent = loadingLabelFor(submitter, form);
                submitter.classList.add('is-loading');
                submitter.setAttribute('aria-busy', 'true');
                submitter.disabled = true;
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        translatePage();
        setupMobileMenu();
        setupToasts();
        setupConfirmations();
        setupDialogs();
        setupFuelRefillCalculator();
        setupRequisitionItemForms();
        setupTransportTableFilter();
        setupTableLoadingStates();
        setupKeyboardShortcuts();
        setupNavigationFeedback();
        setupAccessibleFormFields();
        setupFormSteppers();
        setupStandardForms();
        setupFocusManagement();
    });
    window.addEventListener('pageshow', resetStandardForms);
}());