/* ════════════════════════════════════════════════════════════════════════
   Fair Code - held-out column rows for the proxy check (issues #801-#803)

   Renders "file + column name" rows into a container (add/remove, any number
   of columns, .csv/.tsv/.json/.xlsx) and collects them into the specs that
   FairCodeProfiler.buildHeldOut() turns into a {column: values} map - the
   browser counterpart of repeating --proxy-hints-with PATH=COLUMN. Shared by
   the single-dataset and compare views.
   ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var ACCEPT = '.csv,.tsv,.json,.xlsx,text/csv,application/json,' +
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

  function init(container, addBtn, label) {
    function addRow() {
      var row = document.createElement('div');
      row.className = 'heldout-row';
      var fileLabel = document.createElement('label');
      fileLabel.textContent = 'File ';
      var file = document.createElement('input');
      file.type = 'file';
      file.accept = ACCEPT;
      file.setAttribute('aria-label', label + ' file');
      fileLabel.appendChild(file);
      var colLabel = document.createElement('label');
      colLabel.textContent = 'Column ';
      var col = document.createElement('input');
      col.type = 'text';
      col.className = 'threshold-input';
      col.placeholder = 'e.g. race';
      col.autocomplete = 'off';
      col.setAttribute('aria-label', label + ' column name');
      colLabel.appendChild(col);
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'heldout-remove';
      remove.textContent = '✕';
      remove.setAttribute('aria-label', 'Remove this ' + label + ' column');
      remove.addEventListener('click', function () {
        if (container.children.length > 1) container.removeChild(row);
        else { file.value = ''; col.value = ''; }
      });
      row.appendChild(fileLabel);
      row.appendChild(colLabel);
      row.appendChild(remove);
      container.appendChild(row);
    }
    addRow();
    addBtn.addEventListener('click', addRow);

    // Resolves to [{name, column, data}] for every row the user filled in;
    // throws if a row has only one of file/column. [] means "no held-out test".
    async function collect() {
      var specs = [];
      var rows = Array.prototype.slice.call(container.children);
      for (var i = 0; i < rows.length; i++) {
        var inputs = rows[i].querySelectorAll('input');
        var file = inputs[0].files && inputs[0].files[0];
        var column = inputs[1].value.trim();
        if (!file && !column) continue;
        if (!file || !column) throw new Error('each held-out row needs both a file and a column name');
        var data = /\.xlsx$/i.test(file.name) ? await file.arrayBuffer() : await file.text();
        specs.push({ name: file.name, column: column, data: data });
      }
      return specs;
    }

    return { collect: collect };
  }

  window.FairCodeHeldOut = { init: init };
})();
