FROM admwscki/kicad-kbplacer-primary:7.0.10-lunar

COPY dev-requirements.txt .
RUN pip3 install --no-cache-dir -r dev-requirements.txt && rm dev-requirements.txt

COPY kbplacer/ /tmp/kbplacer

RUN mkdir -p ${HOME}/.local/share/kicad/7.0/3rdparty/plugins && \
    cp -r -n /tmp/kbplacer ${HOME}/.local/share/kicad/7.0/3rdparty/plugins/com_github_adamws_kicad-kbplacer
