/* Fictitious data for design review. Loaded only with ?demo=1. Never ship real data here. */
(function () {
  "use strict";

  function fire(node, type) { node.dispatchEvent(new Event(type, { bubbles: true })); }
  function box(id) { return document.getElementById("f-" + id); }
  function setVal(node, v) { node.value = v; fire(node, "input"); fire(node, "change"); }
  function pick(id, value) {                       // radio / checkbox by exact value
    var n = box(id).querySelector('input[value="' + value.replace(/"/g, '\\"') + '"]');
    if (n && !n.checked) n.click();
  }
  function pickStarts(id, start) {
    var all = box(id).querySelectorAll("input[type=radio],input[type=checkbox]");
    for (var i = 0; i < all.length; i++) if (all[i].value.indexOf(start) === 0) { all[i].click(); return; }
  }
  function checkAll(id) {
    Array.prototype.forEach.call(box(id).querySelectorAll("input[type=checkbox]"), function (c) { if (!c.checked) c.click(); });
  }
  function ins(id, idx) { return box(id).querySelectorAll("input:not([type=radio]):not([type=checkbox]),textarea,select")[idx]; }
  function fillIn(id, vals) {
    vals.forEach(function (v, i) { var n = ins(id, i); if (n && v != null) setVal(n, v); });
  }
  function file(id, name) {
    var inp = box(id).querySelector("input[type=file]");
    var dt = new DataTransfer();
    dt.items.add(new File(["%PDF-1.4 demo"], name, { type: "application/pdf" }));
    inp.files = dt.files; fire(inp, "change");
  }
  function country(id, name) {
    var inp = box(id).querySelector("input");
    inp.focus(); inp.value = name; fire(inp, "input");
    var items = box(id).querySelectorAll(".cs-item");
    for (var i = 0; i < items.length; i++) if (items[i].textContent === name) {
      items[i].dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); break;
    }
  }

  // Section 0
  checkAll("0.1"); checkAll("0.2");
  // A
  pickStarts("A1", "Organization"); pickStarts("A1b", "Nonprofit");
  pick("A2", "1–3 years"); pick("A3", "No");
  setVal(box("A4").querySelector("input"), "20000");
  // B
  setVal(box("B1").querySelector("input"), "Fundación Semillas Digitales (DEMO)");
  country("B2", "Colombia");
  setVal(box("B3").querySelector("input"), "Camila Ejemplo Rojas");
  setVal(box("B4").querySelector("textarea"), "Calle 00 # 00-00, Ciudad Ejemplo, Departamento Ejemplo, 000000");
  setVal(box("B5").querySelector("input"), "85000");
  setVal(box("B7").querySelector("input"), "4");
  setVal(box("B8").querySelector("input"), "DEMO-000000-0");
  setVal(box("B6").querySelector("input"), "https://example.org/semillas-demo");
  // C
  file("C1", "demo-registro-y-estatus.pdf"); file("C2", "demo-w8ben-e.pdf");
  // D
  fillIn("D1", ["Camila Ejemplo Rojas", "Directora", "camila@example.org", "+57 300 000 0000"]);
  pick("D2", "Yes");
  setVal(box("D4").querySelector("input"), "finanzas@example.org");
  // E
  fillIn("E1", ["Bitcoin para comercios de barrio",
    "Capacitamos a 120 comerciantes de dos barrios para recibir pagos en Bitcoin por Lightning y mantener un registro simple de ventas. Cada comercio recibe acompañamiento durante tres meses."]);
  fillIn("E2", ["2027-02-01", "2027-12-15"]);
  setVal(box("E3").querySelector("input"), "Colombia, Ciudad Ejemplo, barrios Norte y Sur");
  setVal(box("E4").querySelector("textarea"), "Los pequeños comercios pagan comisiones altas por cobrar con tarjeta y muchos no tienen acceso a cuentas bancarias. Afecta a dueños de tiendas de barrio, mayormente mujeres. Bitcoin permite cobrar sin intermediarios y recibir el pago el mismo día con costos bajos para ellos.");
  setVal(box("E5").querySelector("input"), "120");
  setVal(box("E6").querySelector("textarea"), "Son dueños de tiendas de barrio y vendedores ambulantes. Los seleccionamos por convocatoria abierta en las juntas de acción comunal con las que trabajamos desde hace tres años; ya nos conocen y confian en nosotros.");
  setVal(box("E7").querySelector("input"), "By December 2027, 80% of 120 trained merchants will have accepted at least 10 Bitcoin payments.");
  setVal(box("E8").querySelector("textarea"), "Los comerciantes aplican lo aprendido en su propio negocio cobrando con QR Lightning. La cooperativa de tenderos Ejemplo, nuestro aliado, se compromete a abastecerles con pagos entre comercios y a promover la aceptación entre sus 300 socios.");
  pick("E9", "Receiving payments"); pick("E9", "Paying");
  (function () {
    var rows = box("E10").querySelectorAll("tbody tr");
    var data = [["Primer taller con 40 comerciantes", "2027-04-30", "Listas de asistencia y fotos"],
                ["60 comercios cobrando con Lightning", "2027-08-15", "Registro de transacciones"],
                ["120 comercios con 10 pagos cada uno", "2027-12-01", "Reporte de pagos y encuesta final"]];
    rows.forEach(function (tr, i) {
      var ins2 = tr.querySelectorAll("input");
      data[i].forEach(function (v, j) { setVal(ins2[j], v); });
    });
  })();
  setVal(box("E11").querySelector("textarea"), "El mayor riesgo es la volatilidad percibida y que los comerciantes dejen de usar la billetera. Lo reducimos con conversión inmediata a pesos opcional, acompañamiento semanal y un grupo de soporte por WhatsApp.");
  pickStarts("E12", "Local circulation");
  setVal(box("E13").querySelector("textarea"), "El dinero circula cuando un comercio recibe un pago en Bitcoin y lo usa para pagar a su proveedor del barrio o a la cooperativa, sin salir de la comunidad. Medimos pagos entre comercios cada mes.");
  // F
  pickStarts("F1", "Commerce");
  fillIn("F2", ["0 merchants", "2027-01-15"]);
  fillIn("F3", ["96 merchants", "2027-12-15"]);
  pick("F4", "Partner or transaction records");
  setVal(box("F5").querySelector("textarea"), "En 2025 capacitamos a 60 personas en dos talleres de educación financiera; 35 hicieron al menos una transacción propia. Informe: https://example.org/informe-2025");
  // G
  setVal(box("G1").querySelector("input"), "32000");
  (function () {
    var cats = box("G4").querySelectorAll(".bline input");
    ["9000", "6000", "2500", "1500", "1000"].forEach(function (v, i) { setVal(cats[i], v); });
  })();
  pick("G3", "Yes");
  (function () {
    var rows = box("G3").querySelectorAll("tbody tr");
    var data = [["Fondo Local Ejemplo", "8000", "confirmed"], ["Alianza Comunitaria Demo", "4000", "pending"]];
    rows.forEach(function (tr, i) {
      var a = tr.querySelectorAll("input"), s = tr.querySelector("select");
      setVal(a[0], data[i][0]); setVal(a[1], data[i][1]); s.value = data[i][2]; fire(s, "change");
    });
  })();
  setVal(box("G7").querySelector("textarea"), "Los comercios seguirán cobrando con Lightning porque ya tienen la billetera y los clientes. La cooperativa Ejemplo sostiene el soporte con una cuota mínima de sus socios y dos voluntarios locales.");
  pickStarts("G8", "Bitcoin");
  // H
  pickStarts("H1", "2.");
  setVal(box("H2").querySelector("textarea"), "Necesitamos un técnico para configurar las billeteras y voluntarios que ayuden con la capacitación en español, además de ayuda con los reportes de seguimiento.");
  // I
  pick("I1", "No");
  setVal(box("I3").querySelector("textarea"), "Recogemos nombre, teléfono y datos de ventas con consentimiento. Se guardan en una hoja protegida con contraseña, solo el equipo de tres personas accede y los borramos a los dos años.");
  // K
  pick("K1", "None"); checkAll("K3"); checkAll("K4");
  setVal(box("K5").querySelector("input"), "Camila Ejemplo Rojas");
})();
