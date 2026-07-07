# Integrar Cloudflare Turnstile en el registro de DMOJ

## Contexto

Fork: `AresLOLXD/dmoj-site` (basado en `DMOJ/online-judge`), con filosofía minimal-diff
para mantener el rebasing fácil contra upstream. Se está detectando registro masivo de
cuentas bot vía `/accounts/register/` (~800 cuentas detectadas por ausencia de
submissions). Ya existe rate limiting en nginx (`limit_req` en
`location = /accounts/register/`). Esta tarea agrega Cloudflare Turnstile como capa
adicional de defensa server-side.

El fork ya tiene una integración opcional de Google reCAPTCHA (`judge/utils/recaptcha.py`,
`ReCaptchaField`/`ReCaptchaWidget` de `snowpenguin`), activa solo si el paquete está
instalado y `settings.RECAPTCHA_PRIVATE_KEY` existe. Turnstile se agrega siguiendo la
misma convención — un campo de formulario opcional e independiente — sin tocar ni
reemplazar esa integración existente.

## Objetivo

Bloquear registros automatizados exigiendo verificación de Cloudflare Turnstile
server-side en el formulario de registro, con el menor diff posible contra upstream y
respetando el patrón que el propio fork ya estableció para reCAPTCHA.

## Decisiones de diseño (acordadas con el usuario)

1. **Integración como campo de formulario Django**, no como chequeo manual en la vista.
   Se sigue el patrón ya usado por `ReCaptchaField`: el campo de Turnstile vive dentro de
   `CustomRegistrationForm`, la validación ocurre en `clean_turnstile()`, y los errores se
   muestran vía `form.turnstile.errors`, igual que los demás campos.
2. **Independiente de reCAPTCHA**, no lo reemplaza. Turnstile es su propio campo,
   condicionado por sus propias settings (`TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`).
   Si en algún momento se habilita también reCAPTCHA, ambos widgets convivirían sin
   conflicto.
3. **Fail-closed ante fallos de red/timeout de la API de Cloudflare.** Si
   `siteverify` no responde o lanza una excepción de red, se trata como verificación
   fallida y se bloquea el registro. Prioriza seguridad sobre disponibilidad — coherente
   con el objetivo de frenar bots, y es el comportamiento que ya proponía el plan
   original del usuario.
4. **No se envía `remote_ip` a Cloudflare.** El parámetro `remoteip` de la API
   `siteverify` es opcional. Omitirlo evita tener que interceptar `get_form_kwargs`/
   inyectar `request` en `RegistrationView`, lo cual habría requerido tocar la clase de
   vista además de la de formulario. Con esta decisión, el único archivo de upstream que
   cambia su contenido de clase es `CustomRegistrationForm` (dentro de
   `judge/views/register.py`); `RegistrationView` queda intacto.

## Cambios a implementar

### 1. Nuevo archivo aislado: `judge/utils/turnstile.py`

Sigue el mismo espíritu aislado que `judge/utils/recaptcha.py` y el mismo estilo de
llamada HTTP defensiva que `judge/utils/pwned.py` (uso de `requests`, ya listado en
`requirements.txt` y usado en otros módulos de `judge/utils/`).

Contiene:

- `TURNSTILE_VERIFY_URL` — constante con el endpoint de Cloudflare
  (`https://challenges.cloudflare.com/turnstile/v0/siteverify`).
- `validate_turnstile(token)` — hace POST a Cloudflare con `secret` (de
  `settings.TURNSTILE_SECRET_KEY`) y `response` (el token). Devuelve `True`/`False` según
  el campo `success` de la respuesta JSON. Cualquier `requests.RequestException` (timeout,
  error de conexión, etc.) se captura y se traduce a `False` (fail-closed), con un
  `log.warning` para diagnóstico, igual que el patrón de `pwned.py`.
- `TurnstileWidget(forms.Widget)` — widget que:
  - Renderiza `<div class="cf-turnstile" data-sitekey="{TURNSTILE_SITE_KEY}"
    data-response-field-name="{name}"></div>`, donde `{name}` es el nombre del campo
    Django (típicamente `turnstile`), de modo que el input oculto que genera el script de
    Cloudflare llega con el nombre que Django espera al parsear el POST — sin necesidad de
    sobrescribir `value_from_datadict`.
  - Declara `class Media: js = ('https://challenges.cloudflare.com/turnstile/v0/api.js',)`
    para que el script se incluya automáticamente a través de `{{ form.media.js }}`, que
    el template de registro ya renderiza — no se agrega ningún `<script>` manual al
    template.

### 2. Settings — `dmoj/local_settings.py` (gitignored, ya excluido vía `.gitignore` línea 9)

```python
TURNSTILE_SITE_KEY = 'PENDIENTE'
TURNSTILE_SECRET_KEY = 'PENDIENTE'
```

### 3. `judge/views/register.py` — solo se modifica `CustomRegistrationForm`

Se importa `validate_turnstile` y `TurnstileWidget` desde `judge.utils.turnstile`. Se
agrega, condicionado a la presencia de `settings.TURNSTILE_SECRET_KEY` (mismo patrón que
el guard existente `if ReCaptchaField is not None:`):

```python
if hasattr(settings, 'TURNSTILE_SECRET_KEY'):
    turnstile = forms.CharField(widget=TurnstileWidget(), required=True, label='')

    def clean_turnstile(self):
        token = self.cleaned_data['turnstile']
        if not validate_turnstile(token):
            raise forms.ValidationError(_('Anti-bot verification failed. Please try again.'))
        return token
```

`RegistrationView` (la clase basada en `OldRegistrationView`) **no se modifica** — ni
`register()`, ni `get_context_data()`, ni ningún método de la vista. La validación ocurre
enteramente dentro del ciclo normal de `form.is_valid()` que el `FormView` de
`django-registration-redux` ya invoca.

### 4. Template — `templates/registration/registration_form.html`

Un solo bloque nuevo en `{% block body %}`, junto al bloque existente de `form.captcha`,
siguiendo el mismo patrón visual:

```html
{% if form.turnstile %}
    <div style="margin-top: 0.5em">{{ form.turnstile }}</div>
    {% if form.turnstile.errors %}
        <div class="form-field-error">{{ form.turnstile.errors }}</div>
    {% endif %}
{% endif %}
```

No se toca `{% block js_media %}` — el script de Turnstile llega solo, vía la
declaración `Media.js` del widget, que se compone dentro de `{{ form.media.js }}`
(ya presente en el template).

## Manejo de errores

- Campo vacío (usuario no completó el widget, o JS de Cloudflare no cargó): error
  estándar de Django "This field is required" en `form.turnstile.errors`.
- Token presente pero inválido, expirado, o `siteverify` devuelve `success: false`: error
  personalizado desde `clean_turnstile()` ("Anti-bot verification failed. Please try
  again.").
- Fallo de red/timeout al llamar a Cloudflare: se trata igual que un token inválido
  (fail-closed) — mismo mensaje de error, se loggea la excepción con `log.warning` para
  diagnóstico operativo, sin exponer detalles internos al usuario.

## Testing

- Test en `judge/tests/` (o módulo equivalente bajo `judge/tests.py` /
  `judge/models/tests/` según convención del proyecto) que mockea
  `judge.utils.turnstile.validate_turnstile` con `unittest.mock.patch` para simular:
  - Verificación exitosa → el registro completa POST y crea la cuenta (inactiva,
    pendiente de activación, como ya hace el flujo existente).
  - Verificación fallida → el POST no crea la cuenta y el form re-renderiza con el error
    en `form.turnstile.errors`.
- No se llama a la API real de Cloudflare en tests (se mockea siempre).

## Criterios de aceptación

- [ ] Registro sin completar el widget de Turnstile es rechazado con mensaje de error
      visible en el form.
- [ ] Registro completando el widget correctamente crea la cuenta con éxito.
- [ ] Un fallo de red al llamar a Cloudflare bloquea el registro (fail-closed).
- [ ] El diff contra upstream se limita a: 1 archivo nuevo (`judge/utils/turnstile.py`),
      un campo + un método `clean_turnstile` dentro de `CustomRegistrationForm` en
      `judge/views/register.py` (sin tocar `RegistrationView`), 2 líneas en
      `local_settings.py`, y un bloque `{% if form.turnstile %}` en el template.
- [ ] `local_settings.py` no se sube a git con las keys reales (ya está en `.gitignore`).
- [ ] `flake8` pasa sin nuevas advertencias.
- [ ] `python manage.py test judge` pasa, incluyendo el nuevo test de registro.

## Notas

- No se usa reCAPTCHA ni hCaptcha para esta nueva capa — decisión ya tomada por el
  usuario (sin dependencia de Google, mejor UX que hCaptcha). La integración existente
  de reCAPTCHA se deja intacta y sigue siendo independiente.
- Turnstile es gratuito sin límite de requests, no requiere que el dominio esté en la red
  de Cloudflare (DNS/proxy) — solo requiere registrar el hostname en el dashboard.
- Se mantiene el rate limiting de nginx ya configurado (`limit_req zone=register_limit`);
  Turnstile es una capa adicional, no un reemplazo.
- `requests` ya está en `requirements.txt` y se usa en otros módulos de `judge/utils/`
  (`pwned.py`, `mathoid.py`, `pdfoid.py`, `texoid.py`); no se agrega ninguna dependencia
  nueva.
